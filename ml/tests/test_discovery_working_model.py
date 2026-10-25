import json
from types import SimpleNamespace

import numpy as np

from zavozik_ml.category_discovery.working_model import clusters,WorkingModel


def row(k,text):
    return dict(content_key=k,semantic_text=text,direction='out',company=k,companies=[k],template_family=k,usable=True)


def test_complete_membership_and_obligation_guard_prevent_bridge_merges():
    rows=[row('a','зарплата'),row('b','заработная плата'),row('c','єсв на зарплату')]
    x=np.array([[1,0],[1,0],[1,0]],np.float32)
    result=clusters([0,1,2],x,rows,.8,set(),'coarse')
    assert [0,1] in result and [2] in result
    assert not any(0 in m and 2 in m for m in result)
    result=clusters([0,1],x,rows,.8,{('a','b')},'fine')
    assert result==[[0],[1]]


def test_runtime_can_return_leaf_coarse_only_unknown_and_insufficient(tmp_path):
    rows=[row('a','зарплата а'),row('b','зарплата б'),row('c','аренда а'),row('d','аренда б'),row('e','кредит а'),row('f','кредит б')]
    x=np.array([[1,0,0],[1,0,0],[0,1,0],[0,1,0],[0,0,1],[0,0,1]],np.float32)
    nodes=[dict(id='salary',level='coarse',parent_id=None,members=[0,1],title='Труд',direction='out'),
           dict(id='salary-leaf',level='fine',parent_id='salary',members=[0,1],title='Зарплата',direction='out'),
           dict(id='rent',level='coarse',parent_id=None,members=[2,3],title='Аренда',direction='out'),
           dict(id='credit',level='coarse',parent_id=None,members=[4,5],title='Обслуживание долга',direction='out')]
    (tmp_path/'records.json').write_text(json.dumps(rows));(tmp_path/'taxonomy.json').write_text(json.dumps(dict(embedding_dimension=3,nodes=nodes,taxonomy_version='test',thresholds={'coarse':dict(threshold=.9),'fine':dict(threshold=.9)})))
    for level in ['coarse','fine']:np.save(tmp_path/(level+'.npy'),x)
    np.savez(tmp_path/'heads.npz',**{level+suffix:value for level in ['coarse','fine'] for suffix,value in [('.weight',np.eye(3,dtype=np.float32)),('.bias',np.zeros(3,np.float32))]})
    model=WorkingModel(tmp_path,load_encoder=False)
    ops=[dict(id=str(i),direction='out') for i in range(4)]
    views=[SimpleNamespace(usable=True,semantic_text='вознаграждение за труд'),SimpleNamespace(usable=True,semantic_text='погашение долга'),SimpleNamespace(usable=True,semantic_text='новый смысл'),SimpleNamespace(usable=False,semantic_text='окончательный расчет')]
    q=np.array([[1,0,0],[0,0,1],[.577,.577,.577],[1,0,0]],np.float32)
    result=model.assign_vectors(ops,views,q)
    assert [r['status'] for r in result]==['assigned','coarse_only','unknown','insufficient_text']
    assert result[0]['category_path']==['salary','salary-leaf']
    assert result[1]['category_id'] is None and result[1]['category_path']==['credit']


def test_refinement_splits_without_refit_and_requires_explicit_fine_evidence(tmp_path):
    from zavozik_ml.category_discovery.working_model import refine_inventory
    src=tmp_path/'source';src.mkdir();review=tmp_path/'review';review.mkdir()
    rows=[dict(row(k,'оплата за '+text),purpose='оплата за '+text,source_domain='case') for k,text in [('a','кофе'),('b','кофе в зернах'),('c','аренду'),('d','аренду помещения')]]
    nodes=[dict(id='parent',level='coarse',parent_id=None,members=[0,1,2,3],title='old',direction='out'),dict(id='leaf',level='fine',parent_id='parent',members=[0,1,2,3],title='old',direction='out')]
    document=dict(nodes=nodes,taxonomy_version='original',thresholds={'coarse':{'threshold':.8},'fine':{'threshold':.8}},selection={'coarse':'fixed','fine':'fixed'})
    (src/'records.json').write_text(json.dumps(rows));(src/'taxonomy.json').write_text(json.dumps(document))
    for level in ['coarse','fine']:np.save(src/(level+'.npy'),np.ones((4,2),np.float32)/np.sqrt(2))
    np.savez(src/'heads.npz',x=np.ones(1))
    labels=[dict(left=rows[0],right=rows[1],coarse='same',fine='same'),dict(left=rows[2],right=rows[3],coarse='same',fine='uncertain')]
    labels.extend(dict(left=rows[a],right=rows[b],coarse='different',fine='different') for a in [0,1] for b in [2,3])
    for r in labels:r['partition']='train'
    (review/'weak_pairs.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in labels))
    result=refine_inventory(src,[review],tmp_path/'out')
    assert result['thresholds']==document['thresholds'] and result['selection']==document['selection']
    assert len([n for n in result['nodes'] if n['level']=='coarse'])==2
    assert len([n for n in result['nodes'] if n['level']=='fine'])==1
    assert json.loads((src/'taxonomy.json').read_text())==document
    import pytest
    labels[0]['partition']='test'
    (review/'weak_pairs.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in labels))
    with pytest.raises(ValueError,match='training evidence only'):
        refine_inventory(src,[review],tmp_path/'forbidden')
    assert not (tmp_path/'forbidden').exists()


def test_inference_retains_known_cannot_links_for_exact_source_inputs(tmp_path):
    rows=[row('a','покупка автомобиля'),row('b','ремонт автомобиля'),row('c','техническое обслуживание')]
    nodes=[dict(id='repair',level='coarse',parent_id=None,members=[1,2],title='Ремонт',direction='out')]
    doc=dict(embedding_dimension=2,nodes=nodes,taxonomy_version='v',thresholds={'coarse':dict(threshold=.8),'fine':dict(threshold=.8)},cannot_link_pairs={'coarse':[['a','b']]})
    (tmp_path/'records.json').write_text(json.dumps(rows));(tmp_path/'taxonomy.json').write_text(json.dumps(doc))
    x=np.tile(np.array([[1.,0]],np.float32),(3,1))
    for level in ['coarse','fine']:np.save(tmp_path/(level+'.npy'),x)
    np.savez(tmp_path/'heads.npz',**{level+suffix:value for level in ['coarse','fine'] for suffix,value in [('.weight',np.eye(2,dtype=np.float32)),('.bias',np.zeros(2,np.float32))]})
    model=WorkingModel(tmp_path,load_encoder=False)
    result=model.assign_vectors([dict(id='query',direction='out')],[SimpleNamespace(usable=True,semantic_text=rows[0]['semantic_text'])],x[:1])
    assert result[0]['status']=='unknown' and result[0]['coarse_category_id'] is None


def test_normalized_purpose_cache_avoids_reencoding_repeated_statement_rows():
    from collections import OrderedDict
    model=WorkingModel.__new__(WorkingModel);model.embedding_cache=OrderedDict();model.document={'embedding_dimension':2}
    calls=[]
    def encoder(texts):
        calls.append(list(texts));return np.array([[len(t),1] for t in texts],dtype=np.float32)
    model.encoder=encoder
    first=model.encode_texts(['аренда','зарплата','аренда'])
    second=model.encode_texts(['зарплата','аренда'])
    assert calls==[['аренда','зарплата']]
    np.testing.assert_array_equal(first[[1,0]],second)
    assert model.encode_texts([]).shape==(0,2)
