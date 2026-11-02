// An independent accompaniment clock plus finite takes and read-only replay.
import {Transport} from './audio.mjs';
import {audioTimeAt} from './timeline.mjs';
import {drumPattern} from './backing.mjs';

export class AttemptTransport extends Transport {
  constructor(callbacks={}) {
    super(callbacks);Object.assign(this,callbacks);
    this.click=false;this.drums=false;this.feel='straight';this.drumVolume=.18;
    this.phase='idle';this.attempt=null;this.replay=null;this.replayVoices=new Set();
  }
  async unlock() {
    await super.unlock();
    if(!this.drumBus){this.drumBus=this.context.createGain();this.drumBus.connect(this.context.destination);}
  }
  configure(playback,bpm) {
    if(this.attempt)return;
    this.playback=playback;this.bpm=this.requestedBpm=bpm;
  }
  ensureClock(defer=false) {
    if(!this.context||this.playing)return;
    this.playing=true;this.beatIndex=0;this.nextTime=this.context.currentTime+.1;this.queue=[];
    this.interval=setInterval(()=>this.schedule(),25);
    const draw=()=>{this.flush();this.draw();if(this.playing)this.animation=requestAnimationFrame(draw);};
    if(!defer)this.schedule();this.animation=requestAnimationFrame(draw);
  }
  setMetronome(value) {this.click=value;if(value)this.ensureClock();}
  setPad(value) {super.setPad(value);if(value)this.ensureClock();}
  setDrums(value) {this.drums=value;if(value)this.ensureClock();}
  performanceAt(audioTime) {
    const stamp=this.context.getOutputTimestamp?.();
    return stamp?.performanceTime>0?stamp.performanceTime+(audioTime-stamp.contextTime)*1000:
      performance.now()+(audioTime-this.context.currentTime)*1000;
  }
  startAttempt(playback,bpm,{countInBars=1,tailBeats=1}={}) {
    if(this.attempt||this.replay)throw Error('Stop the current take or playback first.');
    this.playback=playback;this.bpm=this.requestedBpm=bpm;this.ensureClock(true);
    const beats=playback.beats_per_bar,total=playback.bars.length*beats;
    const countIndex=Math.ceil(this.beatIndex/beats)*beats,startIndex=countIndex+beats*countInBars;
    const start=this.nextTime+(startIndex-this.beatIndex)*60/bpm;
    this.attempt={countIndex,startIndex,total,start,end:start+total*60/bpm,tailEnd:start+(total+tailBeats)*60/bpm,
      bpm,beats,begun:false,ended:false};
    this.phase='countin';
    const performanceTime=this.performanceAt(start);
    this.onScheduled?.({performanceTime,durationMs:total*60000/bpm});
    this.schedule();
    return {performanceTime,durationMs:total*60000/bpm};
  }
  inputPosition(at=performance.now()) {
    const a=this.attempt;if(!a)return null;
    const beat=(audioTimeAt(this.context,at)-a.start)*a.bpm/60;
    if(beat<0||beat>=a.total)return null;
    return {absolute:beat,pass:0,bar:Math.floor(beat/a.beats),beat:beat%a.beats};
  }
  position(at=performance.now()) {
    if(this.attempt)return this.inputPosition(at);
    if(this.replay){const r=this.replay,ms=this.replayPosition();const beat=ms*r.bpm/60000;
      return {absolute:Math.min(beat,r.bars*r.beats),pass:0,bar:Math.min(r.bars-1,Math.floor(beat/r.beats)),
        beat:beat>=r.bars*r.beats?r.beats:beat%r.beats};}
    return null;
  }
  schedule() {
    if(!this.playing)return;
    const now=this.context.currentTime;
    if(this.nextTime<now-.15){this.pause();this.onInterrupt?.('Playback paused after a timing delay. Try starting again.');return;}
    const a=this.attempt,beats=this.playback?.beats_per_bar||4,bars=Math.max(1,this.playback?.bars.length||1);
    while(this.nextTime<now+.1) {
      if(!a)this.bpm=this.requestedBpm;
      const beat=this.beatIndex%beats;
      const counting=a&&this.beatIndex>=a.countIndex&&this.beatIndex<a.startIndex;
      if(this.click||counting)this.tick(this.nextTime,beat===0);
      const local=a?this.beatIndex-a.startIndex:this.beatIndex;
      const backingAllowed=!a||(local>=0&&local<a.total);
      const cycle=((local%(bars*beats))+bars*beats)%(bars*beats);
      if(backingAllowed&&this.padEnabled) {
        if(this.playback?.events) {
          for(const event of this.playback.events)if(event.start>=cycle&&event.start<cycle+1)
            this.note(this.nextTime+(event.start-cycle)*60/this.bpm,event.pitch,event.duration*60/this.bpm);
        } else if(beat===0)this.chord(this.nextTime,this.playback?.bars[Math.floor(cycle/beats)]?.notes||[]);
      }
      if(backingAllowed&&this.drums)for(const event of drumPattern(beats,this.feel))if(Math.floor(event.beat)===beat)
        this.drum(this.nextTime+(event.beat-beat)*60/this.bpm,event.kind,event.level);
      this.queue.push({time:this.nextTime,bar:Math.floor(cycle/beats),beat,bpm:this.bpm,counting});
      this.nextTime+=60/this.bpm;this.beatIndex++;
    }
    const replay=this.replay;
    if(replay&&!replay.paused)while(replay.index<replay.notes.length) {
      const note=replay.notes[replay.index],time=replay.start+(note.at_ms-replay.from)/1000/replay.rate;
      if(time>=now+.12)break;
      replay.index++;
      if(note.sound_end!==null&&note.sound_end>replay.from&&note.at_ms>=replay.from)
        this.replayNote(Math.max(now+.005,time),note.pitch,(note.sound_end-note.at_ms)/1000/replay.rate,note.velocity);
    }
  }
  flush() {
    if(!this.context)return;
    const now=audioTimeAt(this.context,performance.now());
    while(this.queue.length&&this.queue[0].time<=now) {
      const event=this.queue.shift();this.onBeat?.(event);
      if(event.counting)this.onCountIn?.(event.beat+1,this.playback.beats_per_bar);
    }
  }
  draw() {
    const now=audioTimeAt(this.context,performance.now()),a=this.attempt;
    if(a){
      if(now>=a.start&&!a.begun){a.begun=true;this.phase='playing';this.onStart?.();}
      if(a.begun&&!a.ended&&now<a.end)this.onFrame?.(this.position());
      if(now>=a.end&&!a.ended){a.ended=true;this.phase='tail';
        this.onFrame?.({absolute:a.total,pass:0,bar:this.playback.bars.length-1,beat:a.beats});
        this.onAttemptEnd?.(this.performanceAt(a.end));}
      if(now>=a.tailEnd){this.attempt=null;this.phase='idle';this.onAttemptFinished?.();}
    }
    if(this.replay&&!this.replay.paused){this.onReplayFrame?.(this.position(),this.replayPosition());
      if(this.replayPosition()>=this.replay.duration)this.stopReplay();}
    if(!this.attempt&&(!this.replay||this.replay.paused)&&!this.click&&!this.padEnabled&&!this.drums)this.stopClock();
  }
  abortAttempt() {
    if(!this.attempt)return;
    this.attempt=null;this.phase='idle';this.onAbort?.();
  }
  drum(time,kind,level) {
    const gain=this.context.createGain();this.drumBus.gain.value=this.drumVolume;
    gain.gain.setValueAtTime(level,time);gain.gain.exponentialRampToValueAtTime(.0001,time+(kind==='ride'?.18:.08));
    gain.connect(this.drumBus);
    if(kind==='kick'){
      const osc=this.context.createOscillator();osc.frequency.setValueAtTime(110,time);osc.frequency.exponentialRampToValueAtTime(45,time+.08);
      this.voice(osc,gain,time);osc.stop(time+.1);
    }else{
      if(!this.noise){this.noise=this.context.createBuffer(1,this.context.sampleRate*.2,this.context.sampleRate);
        const data=this.noise.getChannelData(0);for(let i=0;i<data.length;i++)data[i]=(Math.random()*2-1)*.3;}
      const source=this.context.createBufferSource();source.buffer=this.noise;this.voice(source,gain,time);source.stop(time+(kind==='ride'?.18:.06));
    }
  }
  replayNote(time,pitch,duration,velocity) {
    const osc=this.context.createOscillator(),gain=this.context.createGain(),level=.18*velocity/127;
    osc.type='triangle';osc.frequency.value=440*2**((pitch-69)/12);
    gain.gain.setValueAtTime(0,time);gain.gain.linearRampToValueAtTime(level,time+.008);
    gain.gain.setTargetAtTime(level*.45,time+.03,.25);gain.gain.setTargetAtTime(.0001,time+Math.max(.01,duration-.035),.012);
    gain.connect(this.context.destination);this.voice(osc,gain,time);this.replayVoices.add(osc);
    const ended=osc.onended;osc.onended=()=>{ended();this.replayVoices.delete(osc);};osc.stop(time+duration+.05);
  }
  playRecording(notes,{bpm,beats,bars,duration,from=0,rate=1}={}) {
    if(this.attempt)throw Error('Finish the current attempt before replaying.');
    this.stopReplay();this.ensureClock();
    this.replay={notes:[...notes].sort((a,b)=>a.at_ms-b.at_ms),bpm,beats,bars,duration,from,rate,
      start:this.context.currentTime+.1,index:0,paused:false};
    // Seeking into a held note reconstructs its remaining sounding duration.
    for(const note of notes)if(note.at_ms<from&&note.sound_end>from)
      this.replayNote(this.replay.start,note.pitch,(note.sound_end-from)/1000/rate,note.velocity);
  }
  replayPosition() {
    const r=this.replay;if(!r)return 0;
    return r.paused?r.from:Math.max(0,Math.min(r.duration,r.from+(audioTimeAt(this.context,performance.now())-r.start)*1000*r.rate));
  }
  pauseReplay() {
    const r=this.replay;if(!r)return;
    r.from=this.replayPosition();r.paused=true;
    for(const osc of this.replayVoices){try{osc.stop(this.context.currentTime);}catch{}}
    this.replayVoices.clear();
  }
  stopReplay() {
    if(!this.replay)return;
    this.pauseReplay();this.replay=null;this.onReplayStop?.();
  }
  stopClock() {
    clearInterval(this.interval);cancelAnimationFrame(this.animation);this.playing=false;this.queue=[];
    for(const voice of this.voices){try{voice.stop(this.context.currentTime);}catch{}}
    this.voices.clear();this.padVoices=[];
  }
  pause() {
    if(this.attempt)this.abortAttempt();this.stopReplay();this.stopClock();
  }
}
