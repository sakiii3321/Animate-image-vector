import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import xml.etree.ElementTree as ET
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from core import DEFAULTS, validate
from potrace_engine import trace_regions
from task_control import TaskControl, ConversionCancelled, run_managed


def fixture():
    labels=np.zeros((64,96),dtype='uint16');records=[]
    for i in range(8):
        x=(i%4)*24;y=(i//4)*32
        labels[y+3:y+29,x+3:x+21]=i+1
        labels[y+10:y+15,x+10:x+15]=0  # transparent hole
        records.append({'id':i+1,'bbox':[x+3,y+3,x+21,y+29],
            'area':int((labels==i+1).sum()),'color':[25+i*25,100,180,128 if i%2 else 255]})
    return labels,records


class ParallelTraceTests(unittest.TestCase):
    def test_parallel_preserves_order_holes_alpha_options_and_empty_paths(self):
        labels,records=fixture()
        for options in ({},{'potrace_alpha_max':0,'potrace_opt_curve':False,'potrace_stroke_width':0,'_spatial_scale':2}, {'potrace_turd_size':100,'_spatial_scale':4}):
            with self.subTest(options=options),tempfile.TemporaryDirectory() as directory:
                directory=Path(directory);outputs=[]
                for threads in (1,4):
                    events=[];output=directory/f'{threads}.svg'
                    trace_regions(labels,records,output,{**DEFAULTS,**options,'potrace_trace_threads':threads},lambda stage,**kw:events.append((stage,kw)))
                    outputs.append(output.read_bytes());ET.fromstring(outputs[-1])
                    self.assertTrue(any(e[1].get('threads')==threads for e in events))
                    self.assertEqual(events[-1][1]['current'],len(records))
                self.assertEqual(*outputs)

    def test_parallel_error_does_not_save_partial_svg(self):
        labels,records=fixture()
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'error.svg'
            with self.assertRaisesRegex(ValueError,'描摹失败'):
                trace_regions(labels,records,output,{**DEFAULTS,'potrace_trace_threads':4,'potrace_turn_policy':'invalid'},lambda *a,**kw:None)
            self.assertFalse(output.exists())

    def test_validation(self):
        for threads in (0,1,4,16):self.assertEqual(validate({'potrace_trace_threads':threads})['potrace_trace_threads'],threads)
        for threads in (-1,17,1.5,True):
            with self.assertRaises(ValueError):validate({'potrace_trace_threads':threads})

    @unittest.skipUnless(os.name=='nt','Windows cancellation')
    def test_cancel_running_node_thread_pool(self):
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory);gate=directory/'start';logpath=directory/'log';output=directory/'out.svg'
            labels=np.tile(np.repeat(np.arange(1,257,dtype='uint16'),2),(512,1));labels.tofile(directory/'regions.bin')
            records=[{'id':i,'bbox':[0,0,512,512],'color':[30,100,180,255]} for i in range(1,257)]
            job=directory/'potrace.json';job.write_text(json.dumps({'width':512,'height':512,'regions':records,'limit':256,'trace_threads':4,'output':str(output)}))
            helper=directory/'helper.py';helper.write_text('import sys,time,subprocess\nfrom pathlib import Path\nwhile not Path(sys.argv[1]).exists():time.sleep(.02)\nsubprocess.run(sys.argv[2:],check=True)\n')
            control=TaskControl();errors=[]
            with logpath.open('wb') as log:
                def run():
                    try:run_managed([sys.executable,str(helper),str(gate),str(ROOT/'runtime/node/node.exe'),str(ROOT/'app/potrace_trace.cjs'),str(job)],log,30,control,gate)
                    except Exception as error:errors.append(error)
                thread=threading.Thread(target=run);thread.start();deadline=time.monotonic()+15;started=False
                while time.monotonic()<deadline and thread.is_alive():
                    lines=logpath.read_text(encoding='utf-8').splitlines()
                    if any(json.loads(line).get('current',0)>0 for line in lines if line.endswith('}')):started=True;break
                    time.sleep(.03)
                control.cancel();thread.join(10)
                self.assertTrue(started,'Worker pool did not report completed work')
                self.assertFalse(thread.is_alive());self.assertIsInstance(errors[0],ConversionCancelled)
                self.assertFalse(output.exists())


if __name__=='__main__':unittest.main(verbosity=2)
