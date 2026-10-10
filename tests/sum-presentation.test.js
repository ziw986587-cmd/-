'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../portal.js'),'utf8');
const fn=source.slice(source.indexOf('function drawPresentation('),source.indexOf('function drawNumbers('));
test('both sum rooms display all sums and retain v3 history shapes',()=>{
  for(const room of ['canada28','australia8ball']){
    const context=vm.createContext({room});vm.runInContext(fn,context);
    for(let total=0;total<=27;total++){
      const numbers=[Math.min(total,9),Math.min(Math.max(total-9,0),9),Math.max(total-18,0)];
      const fan=total%4||4;
      const record={issue:'test',numbers,fan,special:Number(numbers.join(''))%20||20,drawRule:'sum3',settlementRule:'sum-v4'};
      let shown=context.drawPresentation(record);
      assert.equal(shown.displaySpecial,total);assert.equal(shown.fan,fan);
      assert.equal(shown.shape,(total>=14?'大':'小')+' '+(total%2?'单':'双'));
      shown=context.drawPresentation({...record,settlementRule:'sum-v3'});
      assert.equal(shown.shape,(fan>=3?'大':'小')+' '+(fan%2?'单':'双'));
    }
  }
});
test('australia8 new history uses actual eighth number; legacy retains fan shape',()=>{
  const context=vm.createContext({room:'australia8'});vm.runInContext(fn,context);
  for(let number=1;number<=20;number++){
    const numbers=Array.from({length:20},(_,i)=>i+1).filter(n=>n!==number).slice(0,7).concat(number);
    const fan=number%4||4;
    const record={issue:'test',numbers,special:number,fan,settlementRule:'a8-number-v1'};
    assert.equal(context.drawPresentation(record).shape,(number<=10?'小':'大')+' '+(number%2?'单':'双'));
    delete record.settlementRule;
    assert.equal(context.drawPresentation(record).shape,(fan>=3?'大':'小')+' '+(fan%2?'单':'双'));
  }
  assert.ok(context.drawPresentation({issue:'old-zero',numbers:[1,2,3,4,5,6,7,0],special:0,fan:4}));
});
