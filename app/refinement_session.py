"""In-memory candidates and bounded undo for a saved vectorization result.

The caller serializes every operation with AppServer.lock. This module does
not read, write or delete files. Only accept invokes save_result(result), whose
contract is to save a new, independent SVG and pipeline report before returning
a result dict. A failed save leaves the entire session unchanged.

Snapshots isolate mutable metadata. deepcopy shares immutable bytes, so the
original/processed images and SVG buffers are not duplicated by snapshots.
"""
from collections import deque
from copy import deepcopy
import hmac
import math
import secrets


_OMIT = object()
_SOURCE_FIELDS = ('original', 'processed', 'processed_available', 'width', 'height')
_CANDIDATE_FIELDS = ('candidate_id', 'original_result_id')


def _token():
    return secrets.token_urlsafe(24)


def _same_token(supplied, expected):
    return (isinstance(supplied, str) and isinstance(expected, str)
            and supplied.isascii() and expected.isascii()
            and hmac.compare_digest(supplied, expected))


def _json_value(value):
    """Copy JSON metadata, excluding binary buffers even when nested."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            copied = _json_value(item)
            if copied is not _OMIT:
                result[key] = copied
        return result
    if isinstance(value, (list, tuple)):
        items = [_json_value(item) for item in value]
        return [item for item in items if item is not _OMIT]
    return _OMIT


def _validate_result(result, *, saved):
    if not isinstance(result, dict) or not isinstance(result.get('svg'), bytes) or not result['svg']:
        raise ValueError('精修结果缺少有效的 SVG 数据。')
    if saved and (not isinstance(result.get('path'), str) or not result['path']):
        raise ValueError('精修结果尚未保存为独立文件。')
    for key in ('original', 'processed'):
        if result.get(key) is not None and not isinstance(result[key], bytes):
            raise ValueError('精修会话的图片数据必须是不可变字节。')
    count = result.get('refinement_count', 0)
    if type(count) is not int or count < 0:
        raise ValueError('精修版本次数无效。')


class RefinementSession:
    """A single current document, one pending candidate and at most three undos."""

    def __init__(self, history_limit=3):
        if type(history_limit) is not int or not 1 <= history_limit <= 3:
            raise ValueError('精修撤销历史必须保留 1 到 3 步。')
        self._current = None
        self._pending = None
        self._history = deque(maxlen=history_limit)

    @property
    def current(self):
        """An isolated metadata snapshot, with shared immutable image buffers."""
        return deepcopy(self._current)

    def _require_current(self, result_id):
        if self._current is None or not _same_token(result_id, self._current['result_id']):
            raise ValueError('当前结果已更新或失效，请重新选择精修区域。')

    def _require_candidate(self, candidate_id):
        if (self._pending is None
                or not _same_token(candidate_id, self._pending['candidate_id'])
                or self._current is None
                or not _same_token(self._pending['original_result_id'], self._current['result_id'])):
            raise ValueError('精修候选已失效，请重新生成候选。')

    def _summary(self, result):
        result = result or {}
        summary = {
            'path': result.get('path'),
            'bytes': len(result.get('svg', b'')),
            'config': result.get('config', {}),
            'width': result.get('width'),
            'height': result.get('height'),
            'stats': result.get('stats', {}),
            'processed_available': bool(result.get('processed_available', False)),
            'pipeline': result.get('pipeline'),
            'result_id': result.get('result_id'),
            'undo_available': bool(self._history),
            'refinement_count': result.get('refinement_count', 0),
        }
        return {key: None if (copied := _json_value(value)) is _OMIT else copied
                for key, value in summary.items()}

    def metadata(self):
        """The existing conversion response fields plus version/undo metadata."""
        return self._summary(self._current)

    def set_result(self, result):
        """Commit a successful full conversion; failed conversions must not call this."""
        _validate_result(result, saved=True)
        current = deepcopy(result)
        current['result_id'] = _token()
        current['refinement_count'] = result.get('refinement_count', 0)
        for key in _CANDIDATE_FIELDS:
            current.pop(key, None)
        self._current = current
        self._pending = None
        self._history.clear()
        return self.current

    def stage_candidate(self, result_id, candidate):
        """Replace a pending candidate only after a successful refinement.

        candidate is a result patch containing svg:bytes. Source image/canvas
        fields and the saved base path always come from the current document.
        Starting or cancelling work does not call this method, so cancellation
        cannot accidentally discard an earlier preview.
        """
        self._require_current(result_id)
        _validate_result(candidate, saved=False)
        proposed = deepcopy(self._current)
        proposed.update(deepcopy(candidate))
        for key in (*_SOURCE_FIELDS, 'path'):
            if key in self._current:
                proposed[key] = self._current[key]
            else:
                proposed.pop(key, None)
        proposed.update(result_id=result_id, original_result_id=result_id,
                        candidate_id=_token(), refinement_count=self._current.get('refinement_count', 0)+1)
        proposed['refinement_report'] = deepcopy(candidate.get('refinement_report', {}))
        self._pending = proposed
        summary = self._summary(proposed)
        summary.update(path=None, candidate_id=proposed['candidate_id'],
                       original_result_id=result_id)
        report = _json_value(proposed.get('refinement_report', {}))
        summary['report'] = {} if report is _OMIT else report
        return summary

    def get_candidate(self, candidate_id):
        """Return an in-memory preview/save snapshot; never create a file."""
        self._require_candidate(candidate_id)
        return deepcopy(self._pending)

    def discard(self, result_id, candidate_id):
        self._require_current(result_id)
        self._require_candidate(candidate_id)
        self._pending = None
        return self.metadata()

    def accept(self, result_id, candidate_id, save_result):
        """Save a new version, then atomically advance the in-memory session.

        save_result receives a mutable snapshot with the base path for naming.
        It must use a new destination, finish SVG/report writes, and return a
        result dict (a patch containing the new path is also accepted). The
        callback owns filesystem cleanup on failure; this session owns no files.
        """
        self._require_current(result_id)
        self._require_candidate(candidate_id)
        proposed = deepcopy(self._pending)
        for key in _CANDIDATE_FIELDS:
            proposed.pop(key, None)
        new_id = _token()
        proposed['result_id'] = new_id
        proposed['refinement_count'] = self._current.get('refinement_count', 0)+1
        saved = save_result(proposed)
        if not isinstance(saved, dict):
            raise ValueError('精修保存没有返回有效结果，当前版本保持不变。')
        saved = {**proposed, **deepcopy(saved)}
        for key in _SOURCE_FIELDS:
            if key in self._current:
                saved[key] = self._current[key]
            else:
                saved.pop(key, None)
        saved['result_id'] = new_id
        saved['refinement_count'] = self._current.get('refinement_count', 0)+1
        _validate_result(saved, saved=True)
        if saved['path'] in {item['path'] for item in (*self._history, self._current)}:
            raise ValueError('精修必须另存为独立文件，当前版本保持不变。')
        self._history.append(self._current)
        self._current = saved
        self._pending = None
        return self.current

    def undo(self, result_id):
        self._require_current(result_id)
        if not self._history:
            raise ValueError('没有可撤销的精修版本。')
        previous = self._history.pop()
        self._current = {**previous, 'result_id': _token()}
        self._pending = None
        return self.current
