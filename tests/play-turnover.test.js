const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../workbench.js'),'utf8');
const code=source.slice(source.indexOf('function orderEffectiveTurnover('),source.indexOf('function accountSummary('));
const context=vm.createContext({});vm.runInContext(code,context);
const cases=JSON.parse(fs.readFileSync(path.join(__dirname,'turnover-cases.json'),'utf8'));
test('admin effective turnover matches approved play rules and cent rounding',()=>{
 for(const row of cases)for(const status of ['中奖','未中','和局','待开奖','已退单','已取消']){
  const order={...row,status},before=JSON.stringify(order);
  assert.equal(context.orderEffectiveTurnover(order),status==='中奖'?row.expected:status==='未中'?row.amount:0,row.selection+' '+status);
  assert.equal(JSON.stringify(order),before);
 }
});
