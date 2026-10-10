'use strict';
const fs=require('node:fs'),path=require('node:path');
// One writer owns the complete authentication and room data directory.
module.exports=function acquire(directory){
 const file=path.join(directory,'runtime.lock');
 for(let attempt=0;attempt<2;attempt++){
  try{
   const fd=fs.openSync(file,'wx');fs.writeFileSync(fd,JSON.stringify({pid:process.pid}));fs.closeSync(fd);
   process.on('exit',()=>{try{if(JSON.parse(fs.readFileSync(file,'utf8')).pid===process.pid)fs.unlinkSync(file);}catch{}});
   return;
  }catch(error){
   if(error.code!=='EEXIST')throw error;
   let pid;
   try{pid=JSON.parse(fs.readFileSync(file,'utf8')).pid;}catch{throw Error('数据目录正在初始化或锁文件损坏，请先确认没有运行中的软件。');}
   let running=true;
   try{process.kill(pid,0);}catch(e){if(e.code==='ESRCH')running=false;}
   if(running)throw Error('这份数据已有软件实例在运行，请打开已有后台，不要重复启动。');
   fs.unlinkSync(file);
  }
 }
 throw Error('无法取得本地数据锁，请稍后重试。');
};
