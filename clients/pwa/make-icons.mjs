// ORQEVIA command icon v1 ("Orbital Command") generator — zero dependencies,
// no external assets and no network access. Reproduces every committed
// clients/pwa/icons/orqevia-command-v1-*.png from pure geometry (2x2
// supersampling per pixel) and assembles favicon.ico from PNG entries.
// The legacy glyph this file used to draw is removed; the install icon is now
// the ORQEVIA command symbol.
import {writeFileSync} from 'node:fs';
import {deflateSync} from 'node:zlib';

function crc(bytes){let c=0xffffffff;for(const byte of bytes){c^=byte;for(let bit=0;bit<8;bit++)c=(c>>>1)^((c&1)?0xedb88320:0);}return(c^0xffffffff)>>>0;}
function chunk(type,data){const name=Buffer.from(type),len=Buffer.alloc(4),sum=Buffer.alloc(4);len.writeUInt32BE(data.length);sum.writeUInt32BE(crc(Buffer.concat([name,data])));return Buffer.concat([len,name,data,sum]);}
function png(size,rgba){const raw=Buffer.alloc((size*4+1)*size);for(let y=0;y<size;y++){raw[y*(size*4+1)]=0;rgba.copy(raw,y*(size*4+1)+1,y*size*4,(y+1)*size*4);}const header=Buffer.alloc(13);header.writeUInt32BE(size);header.writeUInt32BE(size,4);header[8]=8;header[9]=6;return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',header),chunk('IDAT',deflateSync(raw)),chunk('IEND',Buffer.alloc(0))]);}

const PAL={
  dark:{top:[10,18,30],bot:[4,7,12],ring:[54,197,255],sat:[57,217,138],tick:[201,214,228],inner:[35,59,88],star:[201,214,228]},
  light:{top:[238,244,250],bot:[214,228,242],ring:[14,42,68],sat:[31,169,113],tick:[58,76,96],inner:[176,195,214],star:[14,42,68]},
};
const GAP0=20,GAP1=62;
for(const kind of Object.keys(PAL))PAL[kind].satPoint=[512+300*Math.cos((GAP0+GAP1)/2*Math.PI/180),512+300*Math.sin((GAP0+GAP1)/2*Math.PI/180)];
const STAR=[];for(let k=0;k<8;k++){const a=Math.PI/4*k-Math.PI/2,rr=k%2?26:92;STAR.push([512+rr*Math.cos(a),512+rr*Math.sin(a)]);}
function inStar(x,y){let inside=false;for(let i=0,j=7;i<8;j=i++){const[xi,yi]=STAR[i],[xj,yj]=STAR[j];if(((yi>y)!==(yj>y))&&(x<(xj-xi)*(y-yi)/(yj-yi)+xi))inside=!inside;}return inside;}
function segDist(x,y,x1,y1,x2,y2){const dx=x2-x1,dy=y2-y1,t=Math.max(0,Math.min(1,((x-x1)*dx+(y-y1)*dy)/(dx*dx+dy*dy)));return Math.hypot(x-(x1+t*dx),y-(y1+t*dy));}
const TICKS=[];for(const ang of[270,0,90,180]){const a=ang*Math.PI/180;TICKS.push([512+344*Math.cos(a),512+344*Math.sin(a),512+394*Math.cos(a),512+394*Math.sin(a)]);}
function sample(kind,u,v){const p=PAL[kind],t=v/1024,bg=p.top.map((top,i)=>Math.round(top+(p.bot[i]-top)*t));const dc=Math.hypot(u-512,v-512),ang=Math.atan2(v-512,u-512)*180/Math.PI,norm=((ang%360)+360)%360;if(Math.hypot(u-p.satPoint[0],v-p.satPoint[1])<30)return p.sat;if(Math.abs(dc-300)<=22&&!(norm>=GAP0&&norm<=GAP1))return p.ring;if(Math.abs(dc-212)<=2.5)return p.inner;for(const t4 of TICKS)if(segDist(u,v,t4[0],t4[1],t4[2],t4[3])<=8)return p.tick;if(inStar(u,v))return p.star;return bg;}
function render(kind,size,scale=1){const rgba=Buffer.alloc(size*size*4),off=(1-scale)*512;for(let y=0;y<size;y++)for(let x=0;x<size;x++){let r=0,g=0,b=0;for(const dx of[0.25,0.75])for(const dy of[0.25,0.75]){const c=sample(kind,((x+dx)/size)*1024-off,((y+dy)/size)*1024-off);r+=c[0];g+=c[1];b+=c[2];}const q=(y*size+x)*4;rgba[q]=Math.round(r/4);rgba[q+1]=Math.round(g/4);rgba[q+2]=Math.round(b/4);rgba[q+3]=255;}return png(size,rgba);}
const write=(name,buf)=>writeFileSync(new URL(`./icons/${name}`,import.meta.url),buf);

const outputs=[
  [1024,'orqevia-command-v1-1024.png',1,'dark'],
  [512,'orqevia-command-v1-512.png',1,'dark'],
  [192,'orqevia-command-v1-192.png',1,'dark'],
  [512,'orqevia-command-v1-maskable-512.png',0.78,'dark'],
  [180,'orqevia-command-v1-apple-touch.png',1,'dark'],
  [48,'orqevia-command-v1-favicon-48.png',1,'dark'],
  [32,'orqevia-command-v1-favicon-32.png',1,'dark'],
  [16,'orqevia-command-v1-favicon-16.png',1,'dark'],
  [1024,'orqevia-command-v1-light-1024.png',1,'light'],
];
const built=new Map();
for(const[size,name,scale,kind]of outputs){const buf=render(kind,size,scale);built.set(name,buf);write(name,buf);}

const ico=[48,32,16];
const header=Buffer.alloc(6);header.writeUInt16LE(0,0);header.writeUInt16LE(1,2);header.writeUInt16LE(ico.length,4);
let offset=6+16*ico.length;const parts=[header];
for(const size of ico){const blob=built.get(`orqevia-command-v1-favicon-${size}.png`);const dir=Buffer.alloc(16);dir[0]=size;dir[1]=size;dir.writeUInt16LE(1,4);dir.writeUInt16LE(32,6);dir.writeUInt32LE(blob.length,8);dir.writeUInt32LE(offset,12);parts.push(dir);offset+=blob.length;}
for(const size of ico)parts.push(built.get(`orqevia-command-v1-favicon-${size}.png`));
writeFileSync(new URL('./icons/favicon.ico',import.meta.url),Buffer.concat(parts));

console.log('orqevia-command-v1 icons written:',outputs.length,'png + favicon.ico');
