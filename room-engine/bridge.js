'use strict';
const {spawn}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),readline=require('node:readline');
class RoomBridge {
  constructor(dataDirectory){this.directory=path.join(dataDirectory,'rooms');this.pending=new Map();this.sequence=0;this.child=null;this.starting=null;}
  async start(){
    if(this.starting)return this.starting;
    const bundled=path.join(os.homedir(),'.cache','codex-runtimes','codex-primary-runtime','dependencies','python','python.exe');
    const python=process.env.LOCAL_CENTER_PYTHON||(fs.existsSync(bundled)?bundled:(process.platform==='win32'?'python':'python3'));
    this.starting=new Promise((resolve,reject)=>{
      const child=spawn(python,['-u',path.join(__dirname,'worker.py'),this.directory],{stdio:['pipe','pipe','pipe'],windowsHide:true,env:{...process.env,PYTHONIOENCODING:'utf-8'}});
      this.child=child;
      let ready=false;
      const timeout=setTimeout(()=>{child.kill();reject(Error('房间服务启动超时'));},15000);
      child.on('error',()=>{clearTimeout(timeout);reject(Error('无法启动房间服务，请设置 LOCAL_CENTER_PYTHON 为 Python 3.10+ 的路径'));});
      child.on('exit',()=>{clearTimeout(timeout);this.child=null;this.starting=null;for(const item of this.pending.values()){clearTimeout(item.timer);item.reject(Error('房间服务已停止，请刷新重试'));}this.pending.clear();if(!ready)reject(Error('房间服务未能启动，请查看终端'));});
      child.stderr.on('data',chunk=>process.stderr.write(chunk));
      readline.createInterface({input:child.stdout}).on('line',line=>{
        let msg;try{msg=JSON.parse(line);}catch{return;}
        if(msg.ready){ready=true;clearTimeout(timeout);resolve();return;}
        const item=this.pending.get(msg.id);if(!item)return;clearTimeout(item.timer);this.pending.delete(msg.id);
        if(msg.ok)item.resolve(msg.result);else{let err=Error(msg.message);err.status=msg.status||400;item.reject(err);}
      });
    });
    try{await this.starting;}catch(e){this.starting=null;throw e;}
  }
  async call(method,game='canada28',data={}){
    await this.start();
    return new Promise((resolve,reject)=>{
      const id=++this.sequence;
      const timer=setTimeout(()=>{this.pending.delete(id);reject(Error('房间操作超时，请先刷新确认结果再重试'));},15000);
      this.pending.set(id,{resolve,reject,timer});
      this.child.stdin.write(JSON.stringify({id,method,game,data})+'\n',error=>{if(error){clearTimeout(timer);this.pending.delete(id);reject(error);}});
    });
  }
  close(){if(this.child){this.child.stdin.end();this.child.kill();}}
}
module.exports={RoomBridge};
