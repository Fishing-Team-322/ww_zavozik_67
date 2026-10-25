"""Seal a local, reproducible Qwen research release without activating a backend."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil

from zavozik_ml.classify_v2.model import sha256_file
from .candidate_models import MODELS, verify_base


def seal(inventory, encoder, fit, out):
    if out.exists():raise ValueError('release output already exists')
    spec=MODELS['qwen3-embedding-0.6b'];verify_base(encoder,spec)
    taxonomy=json.loads((inventory/'taxonomy.json').read_text());manifest=json.loads((fit/'manifest.json').read_text())
    if taxonomy['fit_manifest_sha256']!=sha256_file(fit/'manifest.json'):
        raise ValueError('inventory fit provenance differs')
    if taxonomy['source_corpus_sha256']!=manifest['corpus_manifest_sha256'] or taxonomy['source_cache_sha256']!=manifest['cache_manifest_sha256']:
        raise ValueError('inventory training data provenance differs')
    if taxonomy['train_labels_sha256']!=manifest['train_labels_sha256'] or taxonomy['cal_labels_sha256']!=manifest['calibration_labels_sha256']:
        raise ValueError('inventory labels provenance differs')
    if manifest['head_sha256']!=sha256_file(fit/'best_heads.npz'):raise ValueError('trained head checksum differs')
    stage=out.with_name(out.name+'.building')
    if stage.exists():raise ValueError('incomplete release exists; inspect before replacing')
    stage.mkdir(parents=True)
    for name in ('taxonomy.json','records.json','heads.npz','coarse.npy','fine.npy'):shutil.copyfile(inventory/name,stage/name)
    shutil.copytree(encoder,stage/'encoder',symlinks=False)
    provenance=stage/'fit_provenance';provenance.mkdir()
    for name in ('manifest.json','history.json','fit_source.py.txt'):shutil.copyfile(fit/name,provenance/name)
    source=stage/'runtime_source';source.mkdir()
    for path in Path(__file__).parent.glob('*.py'):shutil.copyfile(path,source/path.name)
    projection=dict(taxonomy_version=taxonomy['taxonomy_version'],projection_version=taxonomy['projection_version'],
        fallback='source_text_evidence_v1',source='weak training member consensus plus explicit per-operation source evidence; not independently validated',
        categories={n['id']:dict(forecast_category=n['forecast_category'],flow_role='sales_revenue' if n['forecast_category'].startswith('revenue_') else 'unknown') for n in taxonomy['nodes']})
    (stage/'forecast_projection.json').write_text(json.dumps(projection,ensure_ascii=False,indent=2)+'\n')
    card=dict(status='working_research_not_production_approved',activation=False,encoder=asdict(spec),
        taxonomy_version=taxonomy['taxonomy_version'],native_categories='automatic open two-level inventory; no fixed category enum',
        categories_by_level={level:sum(n['level']==level for n in taxonomy['nodes']) for level in ('coarse','fine')},
        trained_parameters=manifest['trainable_parameters'],full_encoder_fine_tuning=False,selected_views=taxonomy['selection'],
        training_epochs=manifest['epochs_run'],independent_semantic_accuracy=None,
        calibration=dict(train_pairs=sum(manifest['train_label_provenance'].values()),calibration_pairs=sum(manifest['calibration_label_provenance'].values()),scope='weak same-calibration selection; no population accuracy'),
        assignment='all-member cosine; explicit source conflicts; unknown, ambiguous and coarse_only allowed; exact training lookup is not generalization',
        label_source='local Qwen3.5-9B-4bit weak judgments, source-grounded schema and quarantine; teacher can be wrong',
        data_sources=['synthetic Russian commercial case','Spending.gov.ua public Ukrainian/mixed budget snapshot 2021-10-04, CC-BY-4.0, https://spending.gov.ua/'],
        privacy='Payload contains training purpose representatives, potentially public personal names. Treat as payment data; no external inference required.',
        limitations=['No human gold or independently measured economic accuracy','Partial coarse boundary audit is not cluster purity','Fine all-pair teacher agreement can still be wrong','Unknown and ambiguous coverage must be measured on target bank data','Automatic titles are extractive and require product review'],
        cpu='Torch CPU, 1024 dimensions, max256 tokens, four threads; separate process from LightGBM',
        measured_encoder_only={'batch1_p50_ms':860.38,'batch1_p95_ms':1543.29,'peak_rss_mib':1800.2,'samples':12,'not_rpc_or_concurrency':True},
        m6='Separate versioned forecast projection; original purpose, amount and direction retained; field9 schema required. Go routes not connected here.')
    (stage/'model_card.json').write_text(json.dumps(card,ensure_ascii=False,indent=2)+'\n')
    hashes={str(p.relative_to(stage)):sha256_file(p) for p in sorted(stage.rglob('*')) if p.is_file()}
    release=dict(format='working_qwen_release_v1',taxonomy_version=taxonomy['taxonomy_version'],files_sha256=hashes,
                 payload_bytes=sum(p.stat().st_size for p in stage.rglob('*') if p.is_file()),activation=False)
    (stage/'release.json').write_text(json.dumps(release,indent=2)+'\n');stage.rename(out)
    return release


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('inventory','encoder','fit','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();r=seal(a.inventory,a.encoder,a.fit,a.out);print(json.dumps({k:v for k,v in r.items() if k!='files_sha256'},indent=2))


if __name__=='__main__':main()
