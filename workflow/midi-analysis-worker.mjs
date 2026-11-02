import {analyze} from './midi-analysis.mjs';
self.onmessage=event=>{
  try {self.postMessage({id:event.data.id,analysis:analyze(event.data.contract,event.data.messages,event.data.options)});}
  catch {self.postMessage({id:event.data.id,error:'Analysis unavailable'});}
};
