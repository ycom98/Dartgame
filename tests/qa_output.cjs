// Where browser suites write screenshots and result JSON.
// Default: test-output/browser/ (gitignored), so an ordinary test run never rewrites the committed
// evidence in qa-artifacts/. DART_QA_ARTIFACTS overrides it (relative paths are from the repo root);
// `scripts/test.sh browser --record` sets it to qa-artifacts/ to refresh committed evidence on purpose.
const fs=require('fs'),path=require('path');
const root=path.resolve(__dirname,'..');
const dir=path.resolve(root,process.env.DART_QA_ARTIFACTS||path.join('test-output','browser'));
fs.mkdirSync(dir,{recursive:true});
exports.dir=dir;
exports.file=name=>path.join(dir,name);
