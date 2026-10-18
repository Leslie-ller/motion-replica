// Restored Lottie subset -> AE. Original bytes remain in original-snapshot/.
(function () {
    function assert(ok, message) { if (!ok) throw new Error(message); }
    function arr(v) { return v instanceof Array; }
    assert(!(new File(CONFIG.output + "/rebuild.aep")).exists, "Refusing to overwrite existing AEP");
    var old = app.project;
    // Experiment projects are saved inside ownedRoot from the moment they exist, so leftovers from a failed
    // step (even with unsaved changes) are recognisable and replaceable. Anything else is refused.
    if (old && old.numItems > 0) {
        assert(old.file && old.file.fsName.indexOf(CONFIG.ownedRoot + '/') === 0,
               'Refusing to replace a user project or unsaved work');
        old.close(CloseOptions.DO_NOT_SAVE_CHANGES);
    } else if (old) {
        assert(!old.dirty, 'Refusing to replace dirty empty project');
        old.close(CloseOptions.DO_NOT_SAVE_CHANGES);
    }
    app.newProject();
    app.project.save(new File(CONFIG.output + '/rebuild.aep'));
    var proj = app.project, FR = IR.fr, duration = (IR.op - IR.ip) / FR;
    proj.bitsPerChannel = 8;
    proj.linearBlending = false;
    function scalar(v) { return arr(v) ? v[0] : v; }
    function value(v, dimension) {
        if (dimension === 1) return scalar(v);
        var result = v.slice(0, dimension);
        while(result.length < dimension) result.push(0);
        return result;
    }
    // Component j of a Lottie easing value, which may be a scalar or a per-dimension array.
    function part(v, j) { return arr(v) ? (j < v.length ? v[j] : v[0]) : v; }
    function padded(v, dimension) { var r = arr(v) ? v.slice(0, dimension) : [v]; while (r.length < dimension) r.push(0); return r; }
    // Arc length of the spatial cubic s -> s+to -> e+ti -> e (Lottie's to/ti are relative).
    function arcLength(s, e, to, ti) {
        var p1 = [], p2 = [], k, n = 400, total = 0, prev = s.slice(0), cur, t, a, b, c, d, sq;
        for (k = 0; k < s.length; k++) { p1.push(s[k] + (to ? to[k] || 0 : 0)); p2.push(e[k] + (ti ? ti[k] || 0 : 0)); }
        for (var step = 1; step <= n; step++) {
            t = step / n; a = (1-t)*(1-t)*(1-t); b = 3*(1-t)*(1-t)*t; c = 3*(1-t)*t*t; d = t*t*t; cur = []; sq = 0;
            for (k = 0; k < s.length; k++) { cur.push(a*s[k] + b*p1[k] + c*p2[k] + d*e[k]); sq += (cur[k]-prev[k])*(cur[k]-prev[k]); }
            total += Math.sqrt(sq); prev = cur;
        }
        return total;
    }
    // Lottie segment easing (x1,y1,x2,y2 on a unit square) maps exactly to AE speed/influence:
    // out: influence = x1, speed = y1/x1 * dv/dt; in: influence = 1-x2, speed = (1-y2)/(1-x2) * dv/dt.
    function ease(x, y, dv, dt) {
        return new KeyframeEase(x > 1e-6 ? (y / x) * dv / dt : 0, Math.max(0.1, Math.min(100, x * 100)));
    }
    function apply(prop, spec, dimension, spatial) {
        if (!spec) return;
        if(arr(prop.value)) dimension=prop.value.length;
        if (spec.a !== 1) { prop.setValue(value(spec.k, dimension)); return; }
        var keys = spec.k, n = keys.length, i, j;
        for (i = 0; i < n; i++) {
            assert(!keys[i].h && keys[i].e === undefined, 'Hold or legacy keyframes are unsupported here');
            prop.setValueAtTime(keys[i].t / FR, value(keys[i].s, dimension));
        }
        if (spatial) {
            var zero = padded([0], dimension);
            for (i = 0; i < n; i++) {
                var inT = i > 0 && keys[i-1].ti ? padded(keys[i-1].ti, dimension) : zero;
                var outT = i < n-1 && keys[i].to ? padded(keys[i].to, dimension) : zero;
                prop.setSpatialAutoBezierAtKey(i+1, false);
                prop.setSpatialContinuousAtKey(i+1, false);
                prop.setSpatialTangentsAtKey(i+1, inT, outT);
            }
        }
        for (i = 0; i < n; i++) {
            var ei = [], eo = [], count = spatial ? 1 : dimension;
            for (j = 0; j < count; j++) {
                if (i > 0) {
                    var a = keys[i-1], dvIn;
                    if (spatial) dvIn = arcLength(padded(a.s, dimension), padded(keys[i].s, dimension), a.to, a.ti);
                    else dvIn = padded(keys[i].s, count)[j] - padded(a.s, count)[j];
                    ei.push(ease(1 - part(a.i.x, j), 1 - part(a.i.y, j), dvIn, (keys[i].t - a.t) / FR));
                } else ei.push(new KeyframeEase(0, 16.666667));
                if (i < n-1) {
                    var b = keys[i], dvOut;
                    if (spatial) dvOut = arcLength(padded(b.s, dimension), padded(keys[i+1].s, dimension), b.to, b.ti);
                    else dvOut = padded(keys[i+1].s, count)[j] - padded(b.s, count)[j];
                    eo.push(ease(part(b.o.x, j), part(b.o.y, j), dvOut, (keys[i+1].t - b.t) / FR));
                } else eo.push(new KeyframeEase(0, 16.666667));
            }
            prop.setInterpolationTypeAtKey(i+1, KeyframeInterpolationType.BEZIER, KeyframeInterpolationType.BEZIER);
            prop.setTemporalContinuousAtKey(i+1, false);
            prop.setTemporalAutoBezierAtKey(i+1, false);
            prop.setTemporalEaseAtKey(i+1, ei, eo);
        }
    }
    function transform(layer, ks) {
        var t = layer.property('ADBE Transform Group');
        apply(t.property('ADBE Anchor Point'),ks.a,2,true);
        apply(t.property('ADBE Position'),ks.p,2,true);
        apply(t.property('ADBE Scale'),ks.s,2,false);
        apply(t.property('ADBE Rotate Z'),ks.r,1,false);
        apply(t.property('ADBE Opacity'),ks.o,1,false);
    }
    function applyMaskPath(prop, spec, allowOpen) {
        function makePath(data) {
            assert((data.c || (allowOpen && !spec.a)) && data.v.length===data.i.length && data.v.length===data.o.length, 'Unsupported path topology');
            var result=new Shape();result.vertices=data.v;result.inTangents=data.i;result.outTangents=data.o;result.closed=data.c;
            return result;
        }
        if(!spec.a) {prop.setValue(makePath(spec.k));return;}
        assert(spec.a===1 && spec.k.length>=2, 'Invalid animated mask');
        var keys=spec.k,n=keys[0].s[0].v.length,i;
        for(i=0;i<keys.length;i++) {
            assert((!keys[i].h || keys[i].h===1) && keys[i].s.length===1 && keys[i].s[0].v.length===n, 'Unsupported mask hold/topology change');
            assert(i===0 || keys[i].t>keys[i-1].t, 'Mask times must increase');
            prop.setValueAtTime(keys[i].t/FR,makePath(keys[i].s[0]));
        }
        for(i=0;i<keys.length;i++) {
            var inSmooth=i>0 && keys[i-1].h!==1, outSmooth=i<keys.length-1 && keys[i].h!==1;
            var incoming=inSmooth?keys[i-1].i:{x:0.667,y:1},outgoing=outSmooth?keys[i].o:{x:0.333,y:0};
            assert(scalar(incoming.y)===1 && scalar(outgoing.y)===0, 'Unsupported mask easing slopes');
            prop.setTemporalEaseAtKey(i+1,[new KeyframeEase(0,(1-scalar(incoming.x))*100)],[new KeyframeEase(0,scalar(outgoing.x)*100)]);
            prop.setInterpolationTypeAtKey(i+1,inSmooth?KeyframeInterpolationType.BEZIER:KeyframeInterpolationType.LINEAR,keys[i].h===1?KeyframeInterpolationType.HOLD:(outSmooth?KeyframeInterpolationType.BEZIER:KeyframeInterpolationType.LINEAR));
        }
    }
    function shape(comp, L) {
        var layer = comp.layers.addShape();
        // Set source timing before writing comp-time keys; later changes shift them.
        layer.startTime=L.st/FR;
        // Lottie item order matches AE's top-to-bottom content order; addProperty appends, so order is kept.
        function content(container, items) {
            for (var j=0;j<items.length;j++) {
                var s=items[j],p;
                assert(!s.hd,'Hidden shapes are unsupported');
                if (s.ty === 'gr') {
                    var group = container.addProperty('ADBE Vector Group'), gt = null;
                    content(group.property('ADBE Vectors Group'), s.it);
                    for (var k=0;k<s.it.length;k++) if (s.it[k].ty==='tr') gt=s.it[k];
                    if (gt) {
                        assert(!(gt.sk && gt.sk.k) && !(gt.sa && gt.sa.k),'Group skew is unsupported');
                        var tr=group.property('ADBE Vector Transform Group');
                        apply(tr.property('ADBE Vector Anchor'),gt.a,2,false);
                        apply(tr.property('ADBE Vector Position'),gt.p,2,false);
                        apply(tr.property('ADBE Vector Scale'),gt.s,2,false);
                        apply(tr.property('ADBE Vector Rotation'),gt.r,1,false);
                        apply(tr.property('ADBE Vector Group Opacity'),gt.o,1,false);
                    }
                } else if (s.ty === 'rc' || s.ty === 'el') {
                    var rect=s.ty==='rc', prefix=rect?'ADBE Vector Rect':'ADBE Vector Ellipse';
                    p=container.addProperty(rect?'ADBE Vector Shape - Rect':'ADBE Vector Shape - Ellipse');
                    p.property(prefix+' Size').setValue(s.s.k);
                    p.property(prefix+' Position').setValue(s.p.k);
                    if(rect)p.property(prefix+' Roundness').setValue(s.r.k);
                } else if (s.ty === 'sh') {
                    p=container.addProperty('ADBE Vector Shape - Group');
                    applyMaskPath(p.property('ADBE Vector Shape'), s.ks, true);
                } else if(s.ty==='fl'||s.ty==='st') {
                    var fill=s.ty==='fl', name=fill?'ADBE Vector Fill':'ADBE Vector Stroke';
                    p=container.addProperty(fill?'ADBE Vector Graphic - Fill':'ADBE Vector Graphic - Stroke');
                    p.property(name+' Color').setValue(s.c.k.slice(0,3));
                    p.property(name+' Opacity').setValue(s.o.k);
                    if(fill) p.property('ADBE Vector Fill Rule').setValue(s.r || 1);
                    else {
                        p.property(name+' Width').setValue(s.w.k);
                        // Lottie and AE share enum order: cap butt/round/square, join miter/round/bevel.
                        p.property('ADBE Vector Stroke Line Cap').setValue(s.lc || 2);
                        p.property('ADBE Vector Stroke Line Join').setValue(s.lj || 2);
                        // AE hides Miter Limit unless the join is miter; setting it then throws.
                        if (s.ml !== undefined && (s.lj || 2) === 1) p.property('ADBE Vector Stroke Miter Limit').setValue(s.ml);
                    }
                } else if(s.ty!=='tr') throw new Error('Unsupported shape '+s.ty);
            }
        }
        content(layer.property('ADBE Root Vectors Group'), L.shapes);
        if(L.masksProperties) for(var mi=0;mi<L.masksProperties.length;mi++) {
            var m=L.masksProperties[mi];
            assert(m.mode==='a','Unsupported mask mode');
            var mask=layer.property('ADBE Mask Parade').addProperty('ADBE Mask Atom');
            mask.maskMode=MaskMode.ADD;mask.inverted=!!m.inv;
            applyMaskPath(mask.property('ADBE Mask Shape'),m.pt);
            mask.property('ADBE Mask Opacity').setValue(m.o.k);
            mask.property('ADBE Mask Offset').setValue(m.x ? m.x.k : 0);
        }
        return layer;
    }
    var map={};
    for(var ai=0;ai<IR.assets.length;ai++) {
        var asset=IR.assets[ai];
        map[asset.id]=proj.items.addComp('ir_'+asset.id,asset.w||IR.w,asset.h||IR.h,1,duration,FR);
    }
    function layers(comp, data) {
        for(var i=data.length-1;i>=0;i--) {
            var L=data[i],layer;
            assert(!L.ddd && !L.bm && !L.parent && !L.ef && !L.tm && L.sr===1,'Unsupported layer semantics');
            if(L.ty===4)layer=shape(comp,L);
            else if(L.ty===0) {assert(map[L.refId],'Missing precomp');layer=comp.layers.add(map[L.refId]);}
            else throw new Error('Unsupported layer '+L.ty);
            layer.name=(L.ty===4?'sh_':'ref_')+L.ind;
            layer.startTime=L.st/FR;layer.inPoint=L.ip/FR;layer.outPoint=L.op/FR;
            transform(layer,L.ks);
        }
    }
    for(ai=0;ai<IR.assets.length;ai++)layers(map[IR.assets[ai].id],IR.assets[ai].layers);
    var main=proj.items.addComp('ir_main',IR.w,IR.h,1,duration,FR);
    layers(main,IR.layers);
    main.resolutionFactor=[1,1];
    for(var si=0;si<CONFIG.times.length;si++) {
        var time=CONFIG.times[si];
        main.saveFrameToPng(time,new File(CONFIG.output+'/ae-t'+time.toFixed(6).replace(/0+$/,'').replace(/\.$/,'').replace('.','_')+'.png'));
    }
    proj.save(new File(CONFIG.output+'/rebuild.aep'));
    main.openInViewer();
})();
