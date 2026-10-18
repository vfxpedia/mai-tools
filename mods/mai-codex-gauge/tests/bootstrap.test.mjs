import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

test('Linux bootstrap selects the complete official release with its execution helpers',()=>{
 const text=fs.readFileSync(new URL('../bin/bootstrap-linux.sh',import.meta.url),'utf8');
 assert.match(text,/codex_archive=codex-package-x86_64-unknown-linux-musl\.tar\.gz/);
 assert.match(text,/340801565906a7028f6baaa9ab6853addaef221f0016a1417a7c1ffdd96c21f0/);
 assert.match(text,/codex_executable="\$runtime_root\/bin\/codex"/);
 assert.match(text,/test -x "\$runtime_root\/bin\/codex-code-mode-host"/);
 assert.match(text,/test -x "\$runtime_root\/codex-resources\/bwrap"/);
});
