"""Learned two-level open taxonomy and CPU runtime for the first Qwen release.

Category count/names arise from source training vectors. Complete linkage is
cut separately in learned coarse/fine spaces, with explicit source conflicts.
Scores/thresholds use weak calibration, never a correctness probability.
"""
from collections import Counter
import hashlib
import itertools
import os
import json
from pathlib import Path
import re

import numpy as np

from zavozik_ml.classify_v2.model import sha256_file,unit
from .candidate_models import CandidateEncoder
from .corpus import read_rows
from .metric_evaluation import project,agreement
from .normalization import analyze
from .relation_guard import obligation_evidence,conflict
from .train_metric_heads import load_part


def title(rows,members):
    texts=[rows[i]['semantic_text'] for i in members if rows[i].get('source_domain')=='case'] or [rows[i]['semantic_text'] for i in members]
    stops=set('оплата платеж за по от для при под счет договор согласно згідно вiд від зг no xxxx перечисление поступление выплата средства средств сумма рублей руб плату плата пдв ндс рах акту акт дог повністю перераховано сплата сплачено без сумі январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь вересень жовтень липень серпень'.split())
    stops.update('счету счетам договору договора договором поставки упд акту реестру реестр разовый заказ доплата аванс задержку выплаты вiд згiдно no суму вересня месяца месяц год года текущий окончательный выполненные работы выполненных нак накладной накладна'.split())
    stops.update('накл повністю повнiстю кошти перераховується перераховані xxxxр перерах повн зарплату сплати термін термiн лінії рн факт видаткова но пост другий рахунку отримані отриманi зно виплати виплату виплат нарахований учетoм учетом компенсации і в та до іа тпквкмб ктквкмб сума част опл договір договiр згід витрат накладної'.split())
    terms=Counter()
    for text in texts:
        words=[w for w in re.findall(r'[^\W\d_]{3,}',text.lower()) if w not in stops and 'no' not in w and not w.startswith(('xxxx','identifier'))]
        terms.update(set(words+[a+' '+b for a,b in zip(words,words[1:])]))
    ranked=sorted(terms,key=lambda t:(-terms[t]*(1.4 if ' ' in t else 1),t))
    return (ranked[0] if ranked else texts[0][:60]).capitalize()


def choose_threshold(scores,targets):
    mask=targets>=0;y=targets[mask];s=scores[mask]
    choices=[]
    for threshold in sorted(set(map(float,s))):
        pred=s>=threshold;tp=int(((y==1)&pred).sum());n=int(pred.sum());positive=int((y==1).sum())
        precision=tp/max(n,1);recall=tp/max(positive,1);f1=2*precision*recall/max(precision+recall,1e-12)
        if n>=10 and precision>=.9:choices.append((f1,recall,threshold,precision,n))
    if not choices:raise ValueError('weak calibration cannot support a nontrivial90% precision operating point')
    f1,recall,t,precision,n=max(choices)
    return dict(threshold=t,apparent_precision=precision,apparent_recall=recall,apparent_f1=f1,predicted_same_pairs=n,
        source='same weak calibration cohort; not independent precision',semantic_accuracy=None)


def clusters(indices,z,rows,threshold,negatives,level):
    from scipy.cluster.hierarchy import linkage,fcluster
    from scipy.spatial.distance import squareform
    if len(indices)<2:return []
    x=z[indices];distance=np.clip(1-x@x.T,0,2);np.fill_diagonal(distance,0)
    evidences=[obligation_evidence(rows[i]['semantic_text']) for i in indices]
    for a,b in itertools.combinations(range(len(indices)),2):
        ta,ea=evidences[a];tb,eb=evidences[b]
        forbidden=(bool(ta) and eb or bool(tb) and ea or level=='fine' and bool(ta) and bool(tb) and not ta.intersection(tb))
        if forbidden or tuple(sorted((rows[indices[a]]['content_key'],rows[indices[b]]['content_key']))) in negatives:
            distance[a,b]=distance[b,a]=2
    labels=fcluster(linkage(squareform(distance,checks=False),method='complete'),t=max(1e-7,1-threshold),criterion='distance')
    return [[indices[i] for i in np.flatnonzero(labels==label)] for label in sorted(set(labels))]


def build(corpus,cache,train_labels,cal_labels,heads,out):
    if out.exists():raise ValueError('working taxonomy output is immutable')
    tx,train,_,_=load_part(corpus,cache,train_labels,'train',True,20)
    cx,cal,_,_=load_part(corpus,cache,cal_labels,'calibration',True,20)
    fit=json.loads((heads/'manifest.json').read_text());assert fit['head_sha256']==sha256_file(heads/'best_heads.npz')
    with np.load(heads/'best_heads.npz',allow_pickle=False) as data:learned={k:data[k].copy() for k in data.files}
    dim=tx.shape[1];mean=tx.mean(0);weights={};selection={};thresholds={}
    for j,level in enumerate(('coarse','fine')):
        candidates={'original':cx,'centered':unit(cx-mean),'adapted':project(cx,learned,level)}
        reports={name:agreement((z[cal[:,0]]*z[cal[:,1]]).sum(1),cal[:,j+2]) for name,z in candidates.items()}
        selected=max(reports,key=lambda name:(reports[name]['average_precision'],name=='centered'))
        weights[level+'.weight']=learned[level+'.weight'] if selected=='adapted' else np.eye(dim,dtype=np.float32)
        weights[level+'.bias']=learned[level+'.bias'] if selected=='adapted' else -mean if selected=='centered' else np.zeros(dim,np.float32)
        z=candidates[selected];thresholds[level]=choose_threshold((z[cal[:,0]]*z[cal[:,1]]).sum(1),cal[:,j+2]);selection[level]=dict(selected=selected,comparisons=reports)
    rows=read_rows(corpus/'train_unique.jsonl');all_z={level:project(tx,weights,level) for level in ('coarse','fine')}
    case=[i for i,r in enumerate(rows) if r['usable'] and r.get('source_domain')=='case'];public=[i for i,r in enumerate(rows) if r['usable'] and r.get('source_domain')=='public'];keep=set(case)
    # Source training examples only. Auxiliary public neighbors add independent
    # support without replacing the target-domain inventory with budget topics.
    for level,z in all_z.items():
        for i in case:
            eligible=[j for j in public if rows[j]['direction']==rows[i]['direction']]
            if eligible:
                scores=z[eligible]@z[i]
                keep.update(eligible[int(k)] for k in np.argsort(-scores)[:2] if scores[int(k)]>=.35)
    ids=sorted(keep);rows=[rows[i] for i in ids];zs={level:z[ids] for level,z in all_z.items()}
    labels=read_rows(train_labels);neg={level:{tuple(sorted((r['left']['content_key'],r['right']['content_key']))) for r in labels if r[level]=='different'} for level in ('coarse','fine')}
    def support(m):return dict(members=len(m),families=len({rows[i]['template_family'] for i in m}),companies=len({c for i in m for c in rows[i]['companies']}))
    def supported(m):
        s=support(m);return s['members']>=2 and s['families']>=2 and s['companies']>=2
    def node(level,m,parent=None):
        from .forecast_evidence import hint
        identity='qwen-'+level+'-'+hashlib.sha256('|'.join(sorted(rows[i]['content_key'] for i in m)).encode()).hexdigest()[:20]
        known=[hint(rows[i]['purpose'],rows[i]['direction']) for i in m];known=[c for c in known if c!='other']
        forecast=known[0] if len(known)>=2 and len(known)*2>=len(m) and len(set(known))==1 else 'other'
        return dict(id=identity,level=level,parent_id=parent,members=m,title=title(rows,m),title_status='auto_extractive_not_expert_named',support=support(m),direction=rows[m[0]]['direction'],
                    forecast_category=forecast,forecast_evidence_members=len(known),forecast_projection_source='training_member_text_consensus_weak')
    nodes=[]
    for direction in ('in','out'):
        group=[i for i,r in enumerate(rows) if r['direction']==direction]
        for coarse in clusters(group,zs['coarse'],rows,thresholds['coarse']['threshold'],neg['coarse'],'coarse'):
            if not supported(coarse):continue
            parent=node('coarse',coarse);nodes.append(parent)
            for fine in clusters(coarse,zs['fine'],rows,thresholds['fine']['threshold'],neg['fine'],'fine'):
                if supported(fine):nodes.append(node('fine',fine,parent['id']))
    document=dict(format='working_qwen_open_taxonomy_v1',embedding_dimension=dim,nodes=nodes,thresholds=thresholds,
        selection=selection,status='working_research_weak_supervision_not_independently_validated',semantic_accuracy=None,
        final_test_read=False,source_corpus_sha256=sha256_file(corpus/'manifest.json'),source_cache_sha256=sha256_file(cache/'manifest.json'),
        fit_manifest_sha256=sha256_file(heads/'manifest.json'),train_labels_sha256=sha256_file(train_labels),cal_labels_sha256=sha256_file(cal_labels),
        support_requirements=dict(min_members=2,min_families=2,min_companies=2),native_category_vocabulary='discovered_not_fixed',
        assignment_policy='all-member minimum relation cosine plus explicit obligation guard; unknown/coarse_only/ambiguous allowed')
    document['taxonomy_version']='qwen-taxonomy-'+hashlib.sha256(json.dumps(document,sort_keys=True).encode()).hexdigest()[:20]
    document['projection_version']='qwen-projection-'+document['taxonomy_version'].rsplit('-',1)[1]
    out.mkdir(parents=True);np.savez(out/'heads.npz',**weights)
    for level,z in zs.items():np.save(out/(level+'.npy'),z,allow_pickle=False)
    write=(out/'records.json');write.write_text(json.dumps(rows,ensure_ascii=False)+'\n')
    (out/'taxonomy.json').write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n')
    return document

def refine_inventory(source, audit_directories, out, *, training_labels=None):
    """Split existing training groups using additional weak train evidence.

    No new joins, fitting, threshold selection, calibration or test reads.
    Fine nodes require a valid SAME judgment for every member pair. Coarse
    boundary reviews are partial evidence, explicitly not a purity guarantee.
    Invalid/uncertain responses never authorize a fine join.
    """
    import copy
    import shutil
    if out.exists():raise ValueError('refined inventory output is immutable')
    doc=json.loads((source/'taxonomy.json').read_text())
    rows=json.loads((source/'records.json').read_text())
    zs={level:np.load(source/(level+'.npy'),allow_pickle=False) for level in ('coarse','fine')}
    relations={level:{} for level in ('coarse','fine')};evidence={}
    inputs=[]
    if training_labels:inputs.append(training_labels)
    inputs.extend(p/'weak_pairs.jsonl' for p in audit_directories)
    for path in inputs:
        evidence[str(path)]=sha256_file(path)
        for r in read_rows(path):
            if r.get('partition')!='train':raise ValueError('inventory refinement accepts training evidence only; never calibration/test')
            key=tuple(sorted((r['left']['content_key'],r['right']['content_key'])))
            for level in relations:
                relations[level].setdefault(key,set()).add(r[level])
    negatives={level:{key for key,values in mapping.items() if values!={'same'}} for level,mapping in relations.items()}
    def supported(m):
        return len(m)>=2 and len({rows[i]['template_family'] for i in m})>=2 and len({c for i in m for c in rows[i]['companies']})>=2
    def pairkey(a,b):return tuple(sorted((rows[a]['content_key'],rows[b]['content_key'])))
    new=[]
    def make(old,m,parent):
        n=copy.deepcopy(old);n['members']=m;n['parent_id']=parent
        n['id']='qwen-'+n['level']+'-'+hashlib.sha256('|'.join(sorted(rows[i]['content_key'] for i in m)).encode()).hexdigest()[:20]
        n['title']=title(rows,m);n['support']=dict(members=len(m),families=len({rows[i]['template_family'] for i in m}),companies=len({c for i in m for c in rows[i]['companies']}))
        from .forecast_evidence import hint
        hints=[hint(rows[i]['purpose'],rows[i]['direction']) for i in m];known=[h for h in hints if h!='other']
        n['forecast_category']=known[0] if len(known)>=2 and len(known)*2>=len(m) and len(set(known))==1 else 'other'
        n['forecast_evidence_members']=len(known)
        pairs=list(itertools.combinations(m,2));n['weak_review']=dict(pairs=len(pairs),same=sum(relations[n['level']].get(pairkey(a,b))=={'same'} for a,b in pairs),scope='training_only_local_model_not_human')
        return n
    for old in doc['nodes']:
        if old['level']!='coarse':continue
        for m in clusters(old['members'],zs['coarse'],rows,doc['thresholds']['coarse']['threshold'],negatives['coarse'],'coarse'):
            if not supported(m):continue
            parent=make(old,m,None);new.append(parent)
            for leaf in doc['nodes']:
                if leaf['parent_id']!=old['id']:continue
                subset=sorted(set(m).intersection(leaf['members']))
                # Complete linkage forbids any pair without explicit fine SAME.
                forbidden=set(negatives['fine'])
                forbidden.update(pairkey(a,b) for a,b in itertools.combinations(subset,2) if relations['fine'].get(pairkey(a,b))!={'same'} or conflict(rows[a]['semantic_text'],rows[b]['semantic_text'],'fine'))
                for fine in clusters(subset,zs['fine'],rows,doc['thresholds']['fine']['threshold'],forbidden,'fine'):
                    if supported(fine):new.append(make(leaf,fine,parent['id']))
    doc['cannot_link_pairs']={level:[list(k) for k in sorted(values)] for level,values in negatives.items()}
    doc['nodes']=new;doc['refined_from']=doc['taxonomy_version'];doc['training_boundary_evidence_sha256']=evidence
    doc['refinement_policy']='split only; no refit or reselection; every fine member pair explicitly weak-SAME; coarse review partial'
    doc['taxonomy_version']='qwen-taxonomy-'+hashlib.sha256(json.dumps(doc,sort_keys=True).encode()).hexdigest()[:20]
    doc['projection_version']='qwen-projection-'+doc['taxonomy_version'].rsplit('-',1)[1]
    out.mkdir(parents=True)
    for name in ('heads.npz','records.json','coarse.npy','fine.npy'):shutil.copyfile(source/name,out/name)
    (out/'taxonomy.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    return doc


class WorkingModel:
    def __init__(self,directory,*,load_encoder=True):
        self.directory=Path(directory)
        if load_encoder or (self.directory/'release.json').exists():
            meta=json.loads((self.directory/'release.json').read_text())
            actual={str(q.relative_to(self.directory)) for q in self.directory.rglob('*') if q.is_file() and q.name!='release.json'}
            if actual!=set(meta['files_sha256']):raise ValueError('incomplete working release payload')
            for name,digest in meta['files_sha256'].items():
                q=self.directory/name
                if Path(name).is_absolute() or '..' in Path(name).parts or q.is_symlink() or sha256_file(q)!=digest:raise ValueError('working release checksum mismatch')
        self.document=json.loads((self.directory/'taxonomy.json').read_text());self.rows=json.loads((self.directory/'records.json').read_text())
        with np.load(self.directory/'heads.npz',allow_pickle=False) as data:self.weights={k:data[k].copy() for k in data.files}
        self.vectors={level:np.load(self.directory/(level+'.npy'),allow_pickle=False) for level in ('coarse','fine')}
        self.encoder=CandidateEncoder('qwen3-embedding-0.6b',self.directory/'encoder',device='cpu',batch_size=max(1,min(8,int(os.getenv('QWEN_BATCH_SIZE','1')))),threads=max(1,min(4,int(os.getenv('QWEN_THREADS','1'))))) if load_encoder else None
        self.nodes=self.document['nodes'];self.version=self.document['taxonomy_version']
        self.cannot_links={level:{tuple(k) for k in self.document.get('cannot_link_pairs',{}).get(level,[])} for level in ('coarse','fine')}
        dim=self.document['embedding_dimension']
        for level,z in self.vectors.items():
            if z.shape!=(len(self.rows),dim) or not np.isfinite(z).all():raise ValueError('invalid working release vectors')
            project(np.zeros((1,dim),np.float32),self.weights,level)
    def assign_vectors(self,operations,views,x):
        if len(operations)!=len(views) or x.shape!=(len(operations),self.document['embedding_dimension']) or not np.isfinite(x).all():raise ValueError('operation/view/embedding shape or value mismatch')
        ids=[o.get('id') for o in operations]
        if any(not isinstance(i,str) or not i or len(i)>256 for i in ids) or len(set(ids))!=len(ids):raise ValueError('unique nonempty operation ids required')
        if any(o.get('direction') not in ('in','out') for o in operations):raise ValueError('invalid direction')
        zs={level:project(x,self.weights,level) for level in ('coarse','fine')};results=[]
        for i,(op,view) in enumerate(zip(operations,views)):
            base=dict(id=op['id'],category_id=None,coarse_category_id=None,category_path=[],status='unknown',
                      taxonomy_version=self.version,score_kind='weakly_calibrated_relation_cosine_not_probability',candidates=[])
            if not view.usable:results.append(dict(base,status='insufficient_text'));continue
            exact={j for j,r in enumerate(self.rows) if r['direction']==op['direction'] and r['semantic_text']==view.semantic_text}
            exact_keys={self.rows[j]['content_key'] for j in exact}
            def match(n,level):
                if n['direction']!=op['direction']:return None
                if any(tuple(sorted((key,self.rows[j]['content_key']))) in self.cannot_links[level] for key in exact_keys for j in n['members']):return None
                if any(conflict(view.semantic_text,self.rows[j]['semantic_text'],level) for j in n['members']):return None
                score=float((self.vectors[level][n['members']]@zs[level][i]).min())
                return score if score+1e-6>=self.document['thresholds'][level]['threshold'] else None
            coarse=[(n,match(n,'coarse')) for n in self.nodes if n['level']=='coarse']
            coarse=[(n,s) for n,s in coarse if s is not None]
            # Exact source input has a known membership; this is explicitly
            # training lookup, not counted as independent quality.
            exact_nodes=[(n,s) for n,s in coarse if exact.intersection(n['members'])]
            if len(exact_nodes)==1:coarse=exact_nodes
            base['candidates']=[dict(category_id=n['id'],title=n['title'],similarity=s) for n,s in sorted(coarse,key=lambda p:-p[1])[:3]]
            if len(coarse)!=1:results.append(dict(base,status='ambiguous' if coarse else 'unknown'));continue
            parent,score=coarse[0];base.update(coarse_category_id=parent['id'],coarse_category_title=parent['title'],category_path=[parent['id']],status='coarse_only',similarity=score)
            fine=[(n,match(n,'fine')) for n in self.nodes if n['parent_id']==parent['id']];fine=[(n,s) for n,s in fine if s is not None]
            exact_fine=[(n,s) for n,s in fine if exact.intersection(n['members'])]
            if len(exact_fine)==1:fine=exact_fine
            if len(fine)==1:
                leaf,score=fine[0];base.update(category_id=leaf['id'],category_title=leaf['title'],category_path=[parent['id'],leaf['id']],status='assigned',similarity=score)
            results.append(base)
        return results
    def assign(self,operations):
        from .forecast_evidence import hint
        from .classify_compat import auxiliary
        if any(o.get('direction') not in ('in','out') for o in operations):raise ValueError('invalid direction')
        if any(not isinstance(o.get('purpose',''),str) or len(o.get('purpose',''))>8192 for o in operations):raise ValueError('invalid purpose text')
        ids=[o.get('id') for o in operations]
        if any(not isinstance(i,str) or not i or len(i)>256 for i in ids) or len(set(ids))!=len(ids):raise ValueError('unique nonempty operation ids required')
        from .public_corpus import analyze as public_analyze
        views=[(public_analyze if o.get('source_domain')=='public' or re.search(r'[іїєґ]|\b(?:сплата|кошти|послуг|фінансув|пдфо|єсв)\b',o.get('purpose','').lower()) else analyze)(o.get('purpose','')) for o in operations]
        x=self.encoder([v.semantic_text for v in views]);results=self.assign_vectors(operations,views,x)
        for op,result in zip(operations,results):
            result.update(auxiliary(op));result['forecast_category']=hint(op.get('purpose',''),op['direction']);result['forecast_projection_source']='source_text_evidence_v1'
            if result['forecast_category']=='other':
                node=next((n for n in self.nodes if n['id']==(result.get('category_id') or result.get('coarse_category_id'))),None)
                if node and node['forecast_category']!='other':result['forecast_category']=node['forecast_category'];result['forecast_projection_source']=node['forecast_projection_source']
            if result['forecast_category']=='revenue_b2b':
                result['forecast_category']={'card_acquiring':'revenue_acquiring','sbp':'revenue_sbp','cash':'revenue_cash','marketplace_payout':'revenue_marketplace'}.get(result['channel'],'revenue_b2b')
        return results,x
