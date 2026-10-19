"""An owned Node process; the immutable application never writes inside itself."""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import shutil
import subprocess
import time


@contextmanager
def inspector_fixture(folder):
    application=folder/'application';application.mkdir(parents=True)
    marker=folder/'heartbeat.json';diagnostic=folder/'node.err.log'
    rule=application/'rule-ñ😀.cjs';main=application/'main.cjs'
    rule.write_bytes('// original ñ😀\r\nexports.normalize=value=>value<0?0:value>255?255:value+3;\r\n'.encode())
    main.write_text("const fs=require('node:fs'),vm=require('node:vm');const {normalize}=require('./rule-ñ😀.cjs');let tick=0;setInterval(()=>{fs.writeFileSync(process.argv[2],JSON.stringify({tick:++tick,result:normalize(tick%260-2)}));vm.runInNewContext('globalThis.value=128+3',{}, {filename:'virtual-original-ñ.js'});},100);",encoding='utf8')
    (application/'package.json').write_text(json.dumps({'name':'original-inspector-fixture','main':'main.cjs'}),encoding='utf8')
    command=[shutil.which('node'),'--inspect=127.0.0.1:0',str(main),str(marker)]
    process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=diagnostic.open('wb'))
    try:
        end=time.monotonic()+10
        while True:
            text=diagnostic.read_text(encoding='utf8')
            match=re.search(r'ws://127\.0\.0\.1:(\d+)/',text)
            if match and marker.is_file(): break
            assert time.monotonic()<end and process.poll() is None,text
            time.sleep(.05)
        yield {'root':application,'main':main,'rule':rule,'process':process,'marker':marker,'endpoint':'http://127.0.0.1:'+match[1]}
    finally:
        process.terminate();process.wait(timeout=5)
