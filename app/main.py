import argparse
import base64
import hmac
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import webbrowser
from urllib.parse import urlsplit, parse_qs
from core import SCHEMA, DEFAULTS, RETIRED_ENGINE_FIELDS, MAX_INPUT, convert, decode_image, validate, worker, runtime_info, self_test, sanitized_detail
from task_control import TaskControl, ConversionCancelled
from illustration_profiles import PROFILE_LABELS, PROFILE_PRESETS
from refinement_session import RefinementSession

class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self):
        super().__init__(('127.0.0.1', 0), Handler)
        self.token = secrets.token_urlsafe(32)
        self.origin = f'http://127.0.0.1:{self.server_port}'
        self.lock = threading.Lock()
        self.analysis_lock = threading.Lock()
        self.task_lock = threading.Lock()
        self.active_task = None
        self.result = None
        self.refinement = RefinementSession(history_limit=3)
        self.progress = {'running':False, 'stage':'idle'}

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(30)
    def log_message(self, *args):
        pass  # Do not log access tokens or local file paths.
    def respond(self, code, data, content_type='application/json; charset=utf-8', extra=None):
        if isinstance(data, dict):
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        if extra:
            for key, value in extra.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)
    def allowed(self, require_token=True):
        if self.headers.get('Host') != self.server.origin.removeprefix('http://'):
            return False
        origin = self.headers.get('Origin')
        if origin and origin != self.server.origin:
            return False
        if require_token:
            value = self.headers.get('X-App-Token', '')
            return hmac.compare_digest(value, self.server.token)
        return True
    def do_GET(self):
        if not self.allowed(False):
            return self.respond(403, {'error':'禁止访问。'})
        url = urlsplit(self.path)
        if url.path == '/':
            supplied = parse_qs(url.query).get('token', [''])[0]
            if not hmac.compare_digest(supplied, self.server.token):
                return self.respond(403, {'error':'请从启动程序提供的完整本机地址打开。'})
            return self.respond(200, Path(__file__).with_name('index.html').read_bytes(), 'text/html; charset=utf-8')
        if url.path in ('/app.js', '/crop.js', '/refine.js', '/presets.js', '/style.css', '/crop.css'):
            return self.respond(200, Path(__file__).with_name(url.path[1:]).read_bytes(), 'text/javascript; charset=utf-8' if url.path.endswith('.js') else 'text/css; charset=utf-8')
        if not self.allowed():
            return self.respond(403, {'error':'访问令牌无效。'})
        if url.path == '/api/diagnostics':
            return self.respond(200, runtime_info())
        if url.path == '/api/capabilities':
            from enhancement_runtime import runtime_capabilities
            return self.respond(200, runtime_capabilities())
        if url.path == '/api/progress':
            return self.respond(200, self.server.progress)
        if url.path == '/api/original' and self.server.result:
            return self.respond(200, self.server.result['original'], 'image/png')
        if url.path == '/api/processed' and self.server.result and self.server.result.get('processed'):
            return self.respond(200, self.server.result['processed'], 'image/png')
        if url.path == '/api/schema':
            from core import LEGACY_DEFAULTS
            return self.respond(200, {'schema':SCHEMA, 'defaults':DEFAULTS,
                                     'legacy_defaults':LEGACY_DEFAULTS,
                                     'retired_engine_fields':sorted(RETIRED_ENGINE_FIELDS),
                                     'profile_labels':PROFILE_LABELS, 'profile_presets':PROFILE_PRESETS})
        if url.path == '/api/svg' and self.server.result:
            return self.respond(200, self.server.result['svg'], 'image/svg+xml')
        if url.path == '/api/refine-preview':
            if not self.server.lock.acquire(blocking=False):
                return self.respond(409, {'error':'正在处理，请稍后读取精修候选。'})
            try:
                candidate_id = parse_qs(url.query).get('candidate_id', [''])[0]
                candidate = self.server.refinement.get_candidate(candidate_id)
            except ValueError as error:
                return self.respond(400, {'error':str(error)})
            finally:
                self.server.lock.release()
            return self.respond(200, candidate['svg'], 'image/svg+xml')
        return self.respond(404, {'error':'未找到。'})

    def handle_refinement(self, route):
        if self.headers.get_content_type() != 'application/json':
            return self.respond(415, {'error':'请求格式必须为 JSON。'})
        if not self.server.lock.acquire(blocking=False):
            return self.respond(409, {'error':'正在处理，请完成或停止当前任务后再试。'})
        control = None
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                return self.respond(413, {'error':'局部精修请求过大或为空。'})
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise ValueError('请求字段无效。')
            session = self.server.refinement
            current = session.current
            if not current:
                raise ValueError('请先完成图片转换，再圈画需要精修的区域。')
            result_id = request.get('result_id')
            if result_id != current['result_id']:
                raise ValueError('当前结果已更新，请基于最新结果重新圈选。')
            if route == '/api/refine':
                from refinement_jobs import run_refinement
                control = TaskControl()
                with self.server.task_lock:
                    self.server.active_task = control
                def progress(stage, **extra):
                    with self.server.task_lock:
                        self.server.progress = {'running':True, **extra,
                            'stage':'cancelling' if control.cancelled.is_set() else stage}
                progress('refine_prepare')
                candidate = run_refinement(current, request.get('polygon'), request.get('options', {}),
                                           progress=progress, control=control)
                control.begin_save()
                result = session.stage_candidate(result_id, candidate)
                self.server.progress = {'running':False, 'stage':'refine_complete'}
                return self.respond(200, result)
            if route == '/api/refine-accept':
                from refinement_jobs import save_refinement
                session.accept(result_id, request.get('candidate_id'), save_refinement)
            elif route == '/api/refine-undo':
                session.undo(result_id)
            elif route == '/api/refine-discard':
                session.discard(result_id, request.get('candidate_id'))
            self.server.result = session.current
            return self.respond(200, session.metadata())
        except ConversionCancelled:
            self.server.progress = {'running':False, 'stage':'cancelled'}
            return self.respond(200, {'cancelled':True})
        except Exception as error:
            if control:
                self.server.progress = {'running':False, 'stage':'error', 'detail':sanitized_detail(error)}
            return self.respond(400, {'error':sanitized_detail(error) or type(error).__name__})
        finally:
            if control:
                with self.server.task_lock:
                    self.server.active_task = None
            self.server.lock.release()
    def do_POST(self):
        if not self.allowed() or self.headers.get('Origin') != self.server.origin:
            return self.respond(403, {'error':'禁止跨站访问。'})
        route = urlsplit(self.path).path
        if route == '/api/cancel':
            with self.server.task_lock:
                task = self.server.active_task
                accepted = task is not None and task.cancel()
                if accepted:
                    self.server.progress = {'running':True, 'stage':'cancelling'}
            return self.respond(200, {'accepted':accepted})
        if route in ('/api/refine','/api/refine-accept','/api/refine-discard','/api/refine-undo'):
            return self.handle_refinement(route)
        if route == '/api/analyze':
            if self.headers.get_content_type() != 'application/json':
                return self.respond(415, {'error':'请求格式必须为 JSON。'})
            if not self.server.analysis_lock.acquire(blocking=False):
                return self.respond(409, {'error':'上一份图片分析尚未完成，请稍后重新分析。'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= (MAX_INPUT * 4 // 3 + 65536):
                    return self.respond(413, {'error':'请求过大或为空。'})
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError('请求字段无效。')
                from core import crop_box
                from image_recommendation import analyze_image
                config = validate(request.get('config', {}))
                image = decode_image(base64.b64decode(request['image'], validate=True))
                source_size = image.size
                box = crop_box(image.size, config)
                if box:
                    image = image.crop(box)
                result = analyze_image(image)
                result['uncropped_size'] = source_size
                result['crop_box'] = box
                return self.respond(200, result)
            except (ValueError, OSError, TypeError, KeyError) as error:
                return self.respond(400, {'error':sanitized_detail(error)})
            finally:
                self.server.analysis_lock.release()
        if route == '/api/crop-preview':
            # Use the same first frame and EXIF orientation even for files
            # (such as TIFF) that the browser cannot display directly.
            from PIL import Image
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= MAX_INPUT:
                    return self.respond(413, {'error':'图片不能为空，且不能超过 20 MiB。'})
                image = decode_image(self.rfile.read(length))
                width, height = image.size
                image.thumbnail((640, 640), Image.Resampling.LANCZOS)
                preview = io.BytesIO()
                image.save(preview, 'PNG')
                return self.respond(200, preview.getvalue(), 'image/png',
                                    {'X-Source-Width':str(width), 'X-Source-Height':str(height)})
            except (ValueError, OSError) as error:
                return self.respond(400, {'error':sanitized_detail(error)})
        if route == '/api/self-test':
            if not self.server.lock.acquire(blocking=False):
                return self.respond(409, {'error':'正在转换或自检，请稍候。'})
            try:
                return self.respond(200, self_test())
            finally:
                self.server.lock.release()
        if route != '/api/convert':
            return self.respond(404, {'error':'未找到。'})
        if self.headers.get_content_type() != 'application/json':
            return self.respond(415, {'error':'请求格式必须为 JSON。'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= (MAX_INPUT * 4 // 3 + 65536):
                return self.respond(413, {'error':'请求过大或为空。'})
            if not self.server.lock.acquire(blocking=False):
                return self.respond(409, {'error':'正在转换，请稍候。'})
            try:
                control = TaskControl()
                with self.server.task_lock:
                    self.server.active_task = control
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict) or not isinstance(request.get('name'), str):
                    raise ValueError('请求字段无效。')
                data = base64.b64decode(request['image'], validate=True)
                def progress(stage, **extra):
                    with self.server.task_lock:
                        self.server.progress = {'running':True, **extra, 'stage':'cancelling' if control.cancelled.is_set() else stage}
                progress('normalizing')
                result = convert(data, request['name'], request['config'], progress=progress, control=control)
                self.server.result = self.server.refinement.set_result(result)
                self.server.progress = {'running':False, 'stage':'complete'}
                return self.respond(200, self.server.refinement.metadata())
            except ConversionCancelled:
                with self.server.task_lock:
                    self.server.progress = {'running':False, 'stage':'cancelled'}
                return self.respond(200, {'cancelled':True})
            finally:
                with self.server.task_lock:
                    self.server.active_task = None
                self.server.lock.release()
        except Exception as error:
            self.server.progress = {'running':False,'stage':'error','detail':sanitized_detail(error)}
            return self.respond(400, {'error':sanitized_detail(error) or type(error).__name__})

def main():
    parser = argparse.ArgumentParser(description='图片转 SVG（Potrace 插画重构）')
    parser.add_argument('--self-test', action='store_true', help='运行内置图片自检并打印诊断 JSON')
    parser.add_argument('--worker', help=argparse.SUPPRESS)
    parser.add_argument('--refine-worker', help=argparse.SUPPRESS)
    parser.add_argument('--input', type=Path, help='命令行输入图片')
    parser.add_argument('--config', type=Path, help='JSON 配置文件')
    parser.add_argument('--output-directory', help='输出目录；留空使用系统临时目录')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        result = self_test()
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        raise SystemExit(0 if result['ok'] else 1)
    if args.worker:
        worker(args.worker)
        return
    if args.refine_worker:
        from refinement_jobs import worker as refine_worker
        refine_worker(args.refine_worker)
        return
    if args.input:
        config = json.loads(args.config.read_text(encoding='utf-8-sig')) if args.config else {}
        if args.output_directory:
            config['output_directory'] = args.output_directory
        if args.input.stat().st_size > MAX_INPUT:
            raise ValueError('输入文件不能超过 20 MiB。')
        print(convert(args.input.read_bytes(), args.input.name, config)['path'])
        return
    server = AppServer()
    address = server.origin + '/?token=' + server.token
    print('图片转 SVG 已启动。请保持此窗口开启；按 Ctrl+C 退出。\n' + address, flush=True)
    if not args.no_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
