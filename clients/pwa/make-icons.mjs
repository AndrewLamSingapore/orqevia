// Original ORQEVIA Q mark, retaining the dark teal and lime workspace palette.
// Reproducible, antialiased PNGs; no third-party artwork or dependencies.
import {writeFileSync} from 'node:fs';import {deflateSync} from 'node:zlib';
function crc(bytes){let c=0xffffffff;for(const byte of bytes){c^=byte;for(let bit=0;bit<8;bit++)c=(c>>>1)^((c&1)?0xedb88320:0);}return(c^0xffffffff)>>>0;}
function chunk(type,data){const name=Buffer.from(type),len=Buffer.alloc(4),sum=Buffer.alloc(4);len.writeUInt32BE(data.length);sum.writeUInt32BE(crc(Buffer.concat([name,data])));return Buffer.concat([len,name,data,sum]);}
function pixel(x,y){
  const tail=Math.max(0,Math.min(1,((x-78)*15+(y-78)*16)/(15*15+16*16)));
  if(Math.abs(Math.hypot(x-61,y-60)-27)<4.5||Math.hypot(x-(78+tail*15),y-(78+tail*16))<4.5||Math.hypot(x-98,y-37)<4.5)return[213,238,145];
  if(Math.abs(Math.hypot(x-64,y-64)-44)<0.75)return[66,88,73];
  return[17,33,38];
}
for(const [size,name]of[[192,'orqevia-v1-192.png'],[512,'orqevia-v1-512.png'],[180,'orqevia-v1-apple-touch.png']]){
  const raw=Buffer.alloc((size*4+1)*size),samples=4;
  for(let y=0;y<size;y++)for(let x=0;x<size;x++){
    const rgb=[0,0,0];
    for(let sy=0;sy<samples;sy++)for(let sx=0;sx<samples;sx++){const color=pixel((x+(sx+.5)/samples)/size*128,(y+(sy+.5)/samples)/size*128);for(let i=0;i<3;i++)rgb[i]+=color[i];}
    const p=y*(size*4+1)+1+x*4;for(let i=0;i<3;i++)raw[p+i]=Math.round(rgb[i]/(samples*samples));raw[p+3]=255;
  }
  const header=Buffer.alloc(13);header.writeUInt32BE(size);header.writeUInt32BE(size,4);header[8]=8;header[9]=6;
  writeFileSync(new URL(`./icons/${name}`,import.meta.url),Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',header),chunk('IDAT',deflateSync(raw)),chunk('IEND',Buffer.alloc(0))]));
}
