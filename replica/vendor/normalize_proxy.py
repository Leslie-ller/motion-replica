#!/usr/bin/env python3
"""Explicit proxy lowering for the verified benchmark subset. Does not mutate IR.
Positive static axis-aligned rectangle expansion -> rounded offset path (cubic arcs).
Unsupported expansion shapes fail, never silently approximate arbitrary geometry.
"""
import argparse
import copy
import json
import math
from pathlib import Path

def validate_mask_path(spec):
    """Closed paths with fixed topology; animation uses zero-slope temporal easing."""
    def shape(data):
        if not isinstance(data,dict) or data.get('c') is not True:
            raise ValueError('Only closed mask paths are supported')
        points=data.get('v',[])
        if len(points)<3 or len(data.get('i',[]))!=len(points) or len(data.get('o',[]))!=len(points):
            raise ValueError('Invalid mask topology')
        for field in ['v','i','o']:
            for point in data[field]:
                if not isinstance(point,list) or len(point)!=2 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in point):
                    raise ValueError('Invalid mask coordinates')
        return len(points)
    if spec.get('x'):raise ValueError('Mask expressions are unsupported')
    if spec.get('a',0)==0:return shape(spec.get('k'))
    keys=spec.get('k')
    if spec.get('a')!=1 or not isinstance(keys,list) or len(keys)<2:raise ValueError('Invalid animated mask')
    count=None;previous=-math.inf
    for index,key in enumerate(keys):
        t=key.get('t');values=key.get('s')
        if not isinstance(t,(int,float)) or not math.isfinite(t) or t<=previous or not isinstance(values,list) or len(values)!=1 or key.get('h',0) not in (0,1) or 'e' in key:
            raise ValueError('Unsupported mask keys, times or hold')
        previous=t;n=shape(values[0])
        if count is not None and n!=count:raise ValueError('Animated mask topology must stay fixed')
        count=n
        if key.get('h')==1 or index==len(keys)-1:continue
        for side,slope in [('i',1),('o',0)]:
            ease=key.get(side,{});x=ease.get('x');y=ease.get('y')
            x=x[0] if isinstance(x,list) and len(x)==1 else x
            y=y[0] if isinstance(y,list) and len(y)==1 else y
            if not isinstance(x,(int,float)) or not math.isfinite(x) or not 0<x<1 or y!=slope:
                raise ValueError('Mask animation requires zero-slope easing')
    return count

def _number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def validate_keys(spec, where):
    """Modern keyframes with general cubic easing; legacy s/e and holds must be rewritten first."""
    if not isinstance(spec,dict):raise ValueError(f'{where}: missing property')
    if spec.get('x'):raise ValueError(f'{where}: expressions are unsupported')
    if spec.get('a',0)!=1:return False
    keys=spec.get('k')
    if not isinstance(keys,list) or len(keys)<2:raise ValueError(f'{where}: invalid keyframes')
    previous=-math.inf
    for index,key in enumerate(keys):
        if not isinstance(key,dict) or 'e' in key or 's' not in key:
            raise ValueError(f'{where}: legacy or incomplete keyframe; run canonicalize.py first')
        if key.get('h'):raise ValueError(f'{where}: hold keyframes are unsupported on this property')
        t=key.get('t')
        if not _number(t):raise ValueError(f'{where}: key {index} has no numeric time "t"')
        if t<=previous:raise ValueError(f'{where}: key times must increase, but key {index} has t={t} after key {index-1} t={previous}')
        previous=t
        if index==len(keys)-1:continue
        for side in ('i','o'):
            ease=key.get(side)
            if not isinstance(ease,dict):raise ValueError(f'{where}: key {index} lacks easing')
            for axis in ('x','y'):
                values=ease.get(axis);values=values if isinstance(values,list) else [values]
                if not values or any(not _number(v) for v in values):raise ValueError(f'{where}: invalid easing')
                if axis=='x' and any(not 0<=v<=1 for v in values):raise ValueError(f'{where}: easing x must be in 0..1')
    return True

def _tangent_reverses(s, e, to, ti):
    """True when a collinear spatial curve leaves [s,e] or doubles back, so per-axis easing differs from AE."""
    d=[b-a for a,b in zip(s,e)];length=sum(v*v for v in d)
    if length<1e-12:return False
    u1=sum(a*b for a,b in zip(to,d))/length;u2=1+sum(a*b for a,b in zip(ti,d))/length
    # Bezier 0,u1,u2,1 is monotone iff its derivative 3[(u1)B0+(u2-u1)B1+(1-u2)B2] stays >= 0 on [0,1].
    return min(u1*(1-x)**2+(u2-u1)*2*x*(1-x)+(1-u2)*x*x for x in [i/64 for i in range(65)])< -1e-9

def preserve_spatial_tangents(data, changes):
    """lottie-web drops collinear spatial tangents whenever the next key has `s`, using per-axis easing
    instead of arc-length travel. AE always follows the spatial curve. Where the two differ (the curve
    doubles back or overshoots), move the out-tangent 0.01 px off the line so Lottie keeps the curve."""
    for scope,layers in [('root',data['layers'])]+[(a['id'],a.get('layers',[])) for a in data.get('assets',[])]:
        for layer in layers:
            for name in ('p','a'):
                spec=layer.get('ks',{}).get(name,{})
                if spec.get('a')!=1:continue
                keys=spec['k']
                for i in range(len(keys)-1):
                    key=keys[i];s=key['s'];e=keys[i+1]['s'];to=key.get('to');ti=key.get('ti')
                    if not to or not ti:continue
                    if len(s)==3 and not (s[2]==e[2]==0 and to[2]==ti[2]==0):raise ValueError('3D spatial tangents are unsupported')
                    det=lambda p:s[0]*e[1]+s[1]*p[0]+e[0]*p[1]-p[0]*e[1]-p[1]*s[0]-e[0]*s[1]
                    collinear=abs(det([s[0]+to[0],s[1]+to[1]]))<0.001 and abs(det([e[0]+ti[0],e[1]+ti[1]]))<0.001
                    if collinear and _tangent_reverses(s[:2],e[:2],to[:2],ti[:2]):
                        dx,dy=e[0]-s[0],e[1]-s[1];n=math.hypot(dx,dy)
                        key['to']=[to[0]-dy/n*0.01,to[1]+dx/n*0.01]+list(to[2:])
                        changes.append({'layer':f'{scope}/{layer["ind"]}','property':name,'key':i,'nudge_px':0.01,'reason':'keep Lottie on the spatial curve AE uses'})

SHAPE_TYPES={'gr','rc','el','sh','fl','st','tr'}

def validate_shape_path(spec, where):
    """Static shape paths may be open (strokes); animated ones reuse the verified closed-mask rules."""
    if spec.get('a',0)==1:return validate_mask_path(spec)
    data=spec.get('k')
    if spec.get('x') or not isinstance(data,dict) or not isinstance(data.get('c'),bool):raise ValueError(f'{where}: invalid path')
    points=data.get('v',[])
    if len(points)<2 or len(data.get('i',[]))!=len(points) or len(data.get('o',[]))!=len(points):raise ValueError(f'{where}: invalid path topology')
    for field in ('v','i','o'):
        for point in data[field]:
            if not isinstance(point,list) or len(point)!=2 or any(not _number(v) for v in point):raise ValueError(f'{where}: invalid path coordinates')

def validate_shapes(items, where):
    for index,item in enumerate(items):
        ty=item.get('ty');here=f'{where}/{index}:{ty}'
        if ty not in SHAPE_TYPES:raise ValueError(f'{here}: shape type unsupported')
        if item.get('hd'):raise ValueError(f'{here}: hidden shapes unsupported')
        if item.get('bm'):raise ValueError(f'{here}: shape blend modes unsupported')
        if ty=='gr':validate_shapes(item.get('it',[]),here)
        elif ty=='sh':validate_shape_path(item['ks'],here)
        elif ty=='fl':
            if item.get('r',1) not in (1,2):raise ValueError(f'{here}: fill rule must be 1 or 2')
        elif ty=='st':
            if item.get('lc',2) not in (1,2,3) or item.get('lj',2) not in (1,2,3):raise ValueError(f'{here}: invalid stroke cap/join')
            if item.get('d'):raise ValueError(f'{here}: dashed strokes unsupported')
        elif ty=='tr':
            for skew in ('sk','sa'):
                spec=item.get(skew,{'a':0,'k':0})
                if spec.get('a') or spec.get('k'):raise ValueError(f'{here}: group skew unsupported')
        for name,spec in item.items():
            if name in ('ks','it') or not isinstance(spec,dict) or 'k' not in spec:continue
            if validate_keys(spec,f'{here}.{name}'):raise ValueError(f'{here}.{name}: animated shape properties are unsupported')

def layer_opacity(spec):
    """Validate bounded scalar opacity; animated opacity may use general cubic easing."""
    def number(value):
        return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    if spec.get('x'):
        raise ValueError('Opacity expressions are unsupported')
    if spec.get('a',0)==0:
        value=spec.get('k',100)
        if not number(value) or not 0<=value<=100:
            raise ValueError('Static opacity must be in 0..100')
        return value,False
    keys=spec.get('k')
    if spec.get('a')!=1 or not isinstance(keys,list) or len(keys)<2:
        raise ValueError('Invalid animated opacity keys')
    previous=-math.inf
    for key in keys:
        if not isinstance(key,dict):raise ValueError('Invalid opacity key')
        t=key.get('t');v=key.get('s')
        if not number(t) or t<=previous or not isinstance(v,list) or len(v)!=1 or not number(v[0]) or not 0<=v[0]<=100 or key.get('h') or 'e' in key:
            raise ValueError('Unsupported opacity key value/time/hold/end-value')
        previous=t
    validate_keys(spec,'opacity')
    return None,True

def expanded_rectangle(path, amount):
    vertices=path['v']
    if not path.get('c') or len(vertices)!=4 or any(any(abs(v)>1e-9 for v in xy) for key in ('i','o') for xy in path[key]):
        raise ValueError('Mask expansion supports closed straight rectangles only')
    xs=[v[0] for v in vertices];ys=[v[1] for v in vertices]
    x0,x1,y0,y1=min(xs),max(xs),min(ys),max(ys)
    corners={(x0,y0),(x1,y0),(x1,y1),(x0,y1)}
    if set(map(tuple,vertices))!=corners or any(vertices[i][0]!=vertices[(i+1)%4][0] and vertices[i][1]!=vertices[(i+1)%4][1] for i in range(4)):
        raise ValueError('Not an axis-aligned rectangle')
    if amount<0:raise ValueError('Negative mask expansion is unverified')
    if amount==0:return copy.deepcopy(path)
    r=amount;k=r*4*(math.sqrt(2)-1)/3
    return {'c':True,'v':[[x0,y0-r],[x1,y0-r],[x1+r,y0],[x1+r,y1],[x1,y1+r],[x0,y1+r],[x0-r,y1],[x0-r,y0]],'i':[[-k,0],[0,0],[0,-k],[0,0],[k,0],[0,0],[0,k],[0,0]],'o':[[0,0],[k,0],[0,0],[0,k],[0,0],[-k,0],[0,0],[0,-k]]}

def select_renderer(data):
    """Route proven offscreen-opacity cases to SVG; no catch-all error fallback."""
    assets={asset['id']:asset for asset in data.get('assets',[])}
    reasons=[]
    for scope,layers in [('root',data['layers'])]+[(asset['id'],asset.get('layers',[])) for asset in data.get('assets',[])]:
        for layer in layers:
            if any(mask.get('pt',{}).get('a')==1 for mask in layer.get('masksProperties',[])):
                reasons.append(f"{scope}/{layer['ind']}: animated mask path")
            opacity,animated=layer_opacity(layer.get('ks',{}).get('o',{}))
            if animated:
                reasons.append(f"{scope}/{layer['ind']}: animated whole-layer opacity")
            if opacity == 100:continue
            paints=sum(item.get('ty') in ('fl','st','gf','gs') for group in layer.get('shapes',[]) for item in group.get('it',[]))
            if layer['ty']==4 and paints>1:
                reasons.append(f"{scope}/{layer['ind']}: translucent multi-paint layer")
            if layer['ty']==0 and len(assets[layer['refId']].get('layers',[]))>1:
                reasons.append(f"{scope}/{layer['ind']}: translucent multi-layer precomp")
    return ('svg' if reasons else 'canvas'),reasons

def normalize(data, renderer='canvas'):
    if renderer not in ('canvas','svg'):raise ValueError('Unsupported renderer')
    data=copy.deepcopy(data);changes=[]
    assets={a['id']:a for a in data.get('assets',[])}
    for scope,layers in [('root',data['layers'])]+[(a['id'],a.get('layers',[])) for a in data.get('assets',[])]:
        for layer in layers:
            ident=f'{scope}/{layer["ind"]}'
            ks=layer.get('ks',{})
            if isinstance(ks.get('p'),dict) and ks['p'].get('s'):raise ValueError(f'{ident}: separated position unsupported')
            for name in ('a','p','s','r'):
                if name in ks:validate_keys(ks[name],f'{ident}.ks.{name}')
            if layer['ty']==4:validate_shapes(layer.get('shapes',[]),ident)
            opacity,animated=layer_opacity(layer.get('ks',{}).get('o',{}))
            if animated and renderer!='svg':
                raise ValueError('Animated layer opacity requires SVG')
            if opacity != 100:
                if layer['ty']==4:
                    paints=sum(item.get('ty') in ('fl','st','gf','gs') for group in layer.get('shapes',[]) for item in group.get('it',[]))
                    if paints != 1 and renderer=='canvas':
                        raise ValueError('Translucent multi-paint layers require offscreen compositing, not verified')
                elif renderer=='canvas' and layer['ty']==0 and len(assets[layer['refId']].get('layers',[])) != 1:
                    raise ValueError('Translucent multi-layer precomps require offscreen compositing, not verified')
            if layer['ty']==0:
                asset=assets[layer['refId']]
                for key in ('w','h'):
                    if key not in layer:
                        layer[key]=asset.get(key,data[key])
                        changes.append({'layer':ident,'field':key,'value':layer[key],'reason':'asset size or explicit benchmark root-size convention'})
            masks=layer.get('masksProperties',[])
            if masks and not layer.get('hasMask'):
                layer['hasMask']=True;changes.append({'layer':ident,'field':'hasMask','value':True})
            for i,mask in enumerate(masks):
                validate_mask_path(mask['pt'])
                if mask['pt'].get('a')==1 and renderer!='svg':
                    raise ValueError('Animated mask paths require SVG')
                if mask.get('mode')!='a' or mask.get('inv') or mask.get('o',{}).get('k')!=100:
                    raise ValueError('Only non-inverted 100% ADD masks are verified')
                expansion=mask.get('x',{}).get('k',0)
                if not isinstance(expansion,(int,float)) or not math.isfinite(expansion) or mask.get('x',{}).get('a')==1:
                    raise ValueError('Animated expansion is unsupported')
                if expansion:
                    if mask['pt'].get('a',0):raise ValueError('Animated expanded masks unsupported')
                    mask['pt']['k']=expanded_rectangle(mask['pt']['k'],expansion)
                    mask['x']={'a':0,'k':0}
                    changes.append({'layer':ident,'mask':i,'expansion_baked':expansion,'method':'rounded rectangle cubic arcs'})
    preserve_spatial_tangents(data,changes)
    return data,changes

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    data,changes=normalize(json.loads(a.input.read_text()));a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(data,separators=(',',':')));a.out.with_suffix('.changes.json').write_text(json.dumps(changes,indent=2))
