import {makeContract,analyze,decodeNotes} from './midi-analysis.mjs';
let text='';for await(const chunk of process.stdin){text+=chunk;if(text.length>8_000_000)throw Error('Analysis input too large');}
const value=JSON.parse(text);
const result=value.action==='contract'?makeContract(value.score,value.conditions,value.options):
  value.action==='decode'?decodeNotes(value.messages,value.options):analyze(value.contract,value.messages,value.options);
process.stdout.write(JSON.stringify(result));
