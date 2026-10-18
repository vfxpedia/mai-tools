"""TEST ONLY process fixture. Never calls a provider."""
import json
import os
import sys
import time
mode=sys.argv[1]
request=sys.stdin.buffer.read()
if mode=='large':
    for _ in range(256):
        os.write(1,b'A'*65536);os.write(2,b'B'*65536)
elif mode=='utf8':
    data='{"type":"note","text":"한글"}\n'.encode()
    for b in data:os.write(1,bytes([b]))
elif mode=='malformed':os.write(1,b'{partial')
elif mode=='exit':sys.exit(1)
elif mode=='empty':pass
else:
    if mode=='slow':time.sleep(0.15)
    print(json.dumps({'type':'thread.started','thread_id':'12345678-1234-4234-8234-123456789abc'}),flush=True)
    print(json.dumps({'type':'turn.completed','usage':{'input_tokens':2,'output_tokens':1}}),flush=True)
