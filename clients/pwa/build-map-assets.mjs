// Preserve the reviewed upstream bytes; materialize image data URLs for the
// existing closed CSP. No runtime policy, remote dependency or icon is replaced.
import {mkdir,readFile,writeFile,copyFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname,join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';

export const MAPLIBRE_VERSION='6.14.0';
export const UPSTREAM_CSS_SHA256='bacba6a85a867fcf602f2ff88331b8acf7edf3fbd063a519888cfbff39970193';
export const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const DATA_IMAGE=/url\(\s*(?:"(data:image\/[^"]*)"|'(data:image\/[^']*)'|(data:image\/[^)\s]+))\s*\)/g;

export function materializeImages(css){
  const icons=new Map();let occurrences=0;
  const generated=css.replace(DATA_IMAGE,(_match,double,single,bare)=>{
    const uri=double||single||bare,comma=uri.indexOf(',');
    if(uri.slice(0,comma)!=='data:image/svg+xml;charset=utf-8')throw new Error('Unreviewed map image encoding');
    const svg=decodeURIComponent(uri.slice(comma+1));
    if(!/^\s*<svg\b/.test(svg)||/<(?:script|foreignObject|image)\b|\bon[a-z]+\s*=|<!DOCTYPE|\b(?:href|src)\s*=\s*["'](?:https?:|javascript:)/i.test(svg))throw new Error('Unreviewed active map SVG');
    const bytes=Buffer.from(svg,'utf8'),sha256=hash(bytes),path=`/pwa/vendor/maplibre-icons/${sha256}.svg`;
    let icon=icons.get(sha256);
    if(!icon){icon={sha256,path,bytes,occurrences:0,source_data_url_sha256:new Set()};icons.set(sha256,icon);}
    icon.occurrences++;icon.source_data_url_sha256.add(hash(uri));occurrences++;
    return `url("${path}")`;
  });
  if(/data:image\//i.test(generated))throw new Error('Unmaterialized map image URL');
  return {css:generated,occurrences,icons:[...icons.values()].sort((a,b)=>a.sha256.localeCompare(b.sha256))};
}

export async function buildMapAssets(){
  const require=createRequire(import.meta.url),root=dirname(require.resolve('maplibre-gl/package.json'));
  const out=new URL('./vendor/',import.meta.url),sourceCopy=new URL(`../../docs/third-party/maplibre-gl/${MAPLIBRE_VERSION}/`,import.meta.url);
  const pkg=JSON.parse(await readFile(join(root,'package.json'),'utf8'));
  const original=await readFile(join(root,'dist/maplibre-gl.css'));
  if(pkg.version!==MAPLIBRE_VERSION||hash(original)!==UPSTREAM_CSS_SHA256)throw new Error('MapLibre input requires a reviewed version and CSS hash');
  const transformed=materializeImages(original.toString('utf8'));
  if(transformed.occurrences!==39)throw new Error('Reviewed MapLibre image occurrence count changed');
  await mkdir(out,{recursive:true});await mkdir(new URL('maplibre-icons/',out),{recursive:true});await mkdir(sourceCopy,{recursive:true});
  const inputs={};
  for(const name of ['maplibre-gl.mjs','maplibre-gl-shared.mjs','maplibre-gl-worker.mjs']){
    const bytes=await readFile(join(root,'dist',name));inputs[name]={bytes:bytes.length,sha256:hash(bytes)};await copyFile(join(root,'dist',name),new URL(name,out));
  }
  const license=await readFile(join(root,'LICENSE.txt'));
  await copyFile(join(root,'LICENSE.txt'),new URL('MAPLIBRE-LICENSE.txt',out));
  await writeFile(new URL('maplibre-gl.css',sourceCopy),original);
  await writeFile(new URL('maplibre-gl.css',out),transformed.css);
  for(const icon of transformed.icons)await writeFile(new URL(`maplibre-icons/${icon.sha256}.svg`,out),icon.bytes);
  const provenance={schema:'orqevia.maplibre-assets.v1',upstream:{package:'maplibre-gl',version:MAPLIBRE_VERSION,license:'BSD-3-Clause',license_sha256:hash(license),css_sha256:hash(original),css_bytes:original.length,source_copy:`docs/third-party/maplibre-gl/${MAPLIBRE_VERSION}/maplibre-gl.css`,unchanged_modules:inputs},modification:'Percent-decoded original SVG image bytes materialized as same-origin files; CSS image URLs rewritten only. No original image content changed.',generated_css_sha256:hash(transformed.css),image_occurrences:transformed.occurrences,icons:transformed.icons.map(({bytes,source_data_url_sha256,...icon})=>({...icon,bytes:bytes.length,source_data_url_sha256:[...source_data_url_sha256].sort()}))};
  await writeFile(new URL('MAPLIBRE-ASSET-PROVENANCE.json',out),JSON.stringify(provenance,null,2)+'\n');
  const workerURL=new URL('./sw.js',import.meta.url),worker=await readFile(workerURL,'utf8');
  const list=worker.match(/const SHELL=(\[[^;]+\]);/);
  if(!list)throw new Error('Literal shell allowlist is required');
  const previous=JSON.parse(list[1].replaceAll("'",'"'));
  const retained=previous.filter(path=>!path.startsWith('/pwa/vendor/maplibre-icons/')&&!['/pwa/vendor/MAPLIBRE-ASSET-PROVENANCE.json','/pwa/vendor/MAPLIBRE-LICENSE.txt'].includes(path));
  const shell=[...retained,'/pwa/vendor/MAPLIBRE-ASSET-PROVENANCE.json','/pwa/vendor/MAPLIBRE-LICENSE.txt',...transformed.icons.map(icon=>icon.path)];
  await writeFile(workerURL,worker.replace(list[0],`const SHELL=${JSON.stringify(shell).replaceAll('"',"'")};`));
  return {occurrences:transformed.occurrences,icons:transformed.icons.length,upstream_css_sha256:hash(original),generated_css_sha256:hash(transformed.css)};
}

if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))console.log(JSON.stringify(await buildMapAssets()));
