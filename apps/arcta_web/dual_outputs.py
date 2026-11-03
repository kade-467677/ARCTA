"""64H9 : un manifeste, deux dossiers de résultats, un index de capitalisation."""
from dataclasses import replace
from arcta.dual_campaign import MODES, index_sheets


def save_dual_outputs(session, run_id, campaign, *, include_plots, include_pdf):
    from . import session_campaign_run as storage
    artifacts = []
    for basis in MODES:
        produced = storage._save_campaign_outputs(session, run_id,
            campaign.mechanical_results[basis], include_plots=include_plots,
            include_pdf=include_pdf, output_subdir=basis)
        for item in produced:
            artifacts.append({**item, 'kind': item['kind'] + '_' + basis,
                'torque_basis': basis, 'title': basis + ' — ' + str(item.get('title', item['filename']))})
    sheets = index_sheets(campaign)
    bymode = {a['torque_basis']: a for a in artifacts if a['kind'].startswith('XLSX_')}
    sheets['ARCTA_MECHANICAL_MODES']['Workbook_SHA256'] = [bymode[b]['sha256'] for b in MODES]
    index = replace(campaign, result_sheets=sheets, mechanical_results={})
    root = storage._save_campaign_outputs(session, run_id, index,
                                          include_plots=False, include_pdf=False)
    artifacts = [*root, *artifacts]
    metadata = storage.load_campaign_result_metadata(session, run_id)
    metadata.update(mechanical_modes=list(MODES), artifacts=artifacts)
    storage._atomic_json(storage.session_campaign_run_dir(session, run_id) /
                         storage.CAMPAIGN_RUN_RESULT_FILENAME, metadata)
    return tuple(artifacts)
