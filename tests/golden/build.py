import json
raw=json.load(open('raw.json'))
KML={'colorado':('WPI_3168057_130_COLORADO.kml',['P13']),
     'e_second':('1A8J1KB_WPI_3171586_-_E_Second_Street.kml',['MH 223','MH FA']),
     'granite':('1A8G8FM_WPI_3159540_GRANITE1.kml (DIFFERENT JOB: WPI 3159540, poles P28-P32)',['P28','P29','P30','P31','P32'])}
WARN=('W','G20')
def approaches(devs):
    main=[d for d in devs if abs(d['dy_ft'])<=60]
    res={}
    for name,sel in (('from_sheet_left',[d for d in main if d['dx_ft']<0]),('from_sheet_right',[d for d in main if d['dx_ft']>0])):
        seq=sorted([d for d in sel if d['code'].startswith('W')],key=lambda d:-abs(d['dx_ft']))
        sp=[round(abs(seq[i]['dx_ft']-seq[i+1]['dx_ft']),1) for i in range(len(seq)-1)]
        res[name]={'advance_sequence_far_to_near':[d['code'] for d in seq],
                   'positions_ft':[{'code':d['code'],'dx_ft':d['dx_ft'],'dy_ft':d['dy_ft']} for d in seq],
                   'spacing_ft':sp,
                   'end_signs':[{'code':d['code'],'dx_ft':d['dx_ft'],'dy_ft':d['dy_ft']} for d in sel if d['code']=='G20-2' or d['code'].startswith('R2-11')]}
    return res
for job,v in raw.items():
    sheets=[]
    for s in v['sheets']:
        devs=s['devices_at_posts']
        side=[d for d in devs if abs(d['dy_ft'])>60]
        sheets.append({'sheet_number':s['page'],'of':v['sheet_count'],'phase_label':'PHASE '+s['phase'],'scale':s['scale'],
          'work_points':s['work_points'],'approaches_on_main_road':approaches(devs),
          'side_street_devices':side,'all_devices_at_posts':devs,
          'device_counts':{c:sum(1 for d in devs if d['code']==c) for c in sorted({d['code'] for d in devs})},
          'callout_codes':s['callout_codes'],'arrow_board':s['arrow_board'],
          'dimension_labels':s['dimension_labels'],
          'job_notes':[n for n in s['notes_job_specific'] if 'SPEED' in n or 'SIDEWALK' in n or 'ALLOW' in n]})
    g={'_meta':{'golden_version':'0.1','status':'DRAFT - extracted automatically, needs SME check',
       'source_pdf':v['source_pdf'],'matching_kml':KML[job][0],'kml_work_points':KML[job][1],
       'expected_ta':v['expected_ta'],
       'method':'Positions are the centres of the small sign-code labels printed next to each sign post, measured from the mean centre of the work-point labels, converted with the sheet scale (sheet 34 x 22 in, 72 pt per inch). Frame: sheet axes, x to the right, y down, main road roughly along x. Not georeferenced.',
       'expected_error':'about 5 to 15 ft: label offset from the post, and the work-point label is beside the point, not on it',
       'schematic_warning':'Some sheets are not drawn to scale for advance signs. E Second St signs are drawn about 40 ft apart but labelled 100 ft MIN. Where a dimension label exists, compare against the label value, not the drawn position.',
       'approach_classification':'auto: main-road signs within 60 ft of the work point across the road, split by left or right of the work point. Verify by hand near intersections (Granite I, V).',
       'not_captured':'taper, buffer and channelizer geometry (vector shapes), work-vehicle position, dimension meaning (labels kept as text with position only)',
       'compare_rules':{'exact':['expected_ta','sheet count','work points per sheet','scale','advance sequence order per approach','callout code set'],
                        'tolerance_ft':{'sign_position_along_road':15,'sign_spacing':10},
                        'side':'sign must be on the same side of the road (sign of dy relative to the road centre)'}},
       'sheets':sheets}
    json.dump(g,open(f'golden_{job}.json','w'),indent=1)
    print('==',job,v['expected_ta'],len(sheets),'sheets')
    for s in sheets:
        a=s['approaches_on_main_road']
        print(' ',s['phase_label'],s['scale'],s['work_points'],'| L:',a['from_sheet_left']['advance_sequence_far_to_near'],a['from_sheet_left']['spacing_ft'],'| R:',a['from_sheet_right']['advance_sequence_far_to_near'],a['from_sheet_right']['spacing_ft'],'| side:',len(s['side_street_devices']))
