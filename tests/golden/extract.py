import pdfplumber,re,json,glob,statistics,sys
CODE=re.compile(r"^(W\d+-\d+[A-Z]?|G20-\d|R\d+-\d+[A-Z]*|RI-27\.1\.1|M4-\w+)$")
DIM=re.compile(r"^(\d+)'$")
SRC={
 'colorado':('/mnt/user-data/uploads/1793015623689_WPI_3168057_-_130_COLORADO_ST_-_MATTAPAN_-_TMP.pdf','TA-10'),
 'e_second':('/mnt/user-data/uploads/1793015623689_1A8J1KB_WPI_3171586__E_Second_St__South_Boston__MA_-_TMP.pdf','TA-6'),
 'granite':('/mnt/user-data/uploads/1793015623690_1A8L6XS_WPI_3178233_-_125-165_GRANITE_ST__US-1___WESTERLY__RI_-_TMP.pdf','TA-33'),
}
def words(pg):
    return pg.extract_words(keep_blank_chars=False)
out={}
for job,(f,ta) in SRC.items():
    with pdfplumber.open(f) as pdf:
        sheets=[]
        for i,pg in enumerate(pdf.pages):
            W=words(pg); W2=pg.extract_words(extra_attrs=['size']); full=pg.extract_text() or ''
            m=re.search(r"PHASE ([IVX]+)",full); phase=m.group(1) if m else None
            sc=re.findall(r"1\"\s*=\s*(\d+)'",full); scale_ft=int(sc[0]) if sc else None
            ppf=72.0/scale_ft  # sheet plotted 34x22 in at 72 pt/in
            # work point labels
            wp=[]
            for WW in (W,W2):
              for k,w in enumerate(WW):
                t=w['text']
                nxt=WW[k+1]['text'] if k+1<len(WW) else ''
                if re.match(r"^P\.\d",t) or (t=='P.' and re.match(r"^\d",nxt)):
                    lab=t if t!='P.' else 'P.'+nxt
                    if w['x0']<2150 and w['top']<1400: wp.append((lab,(w['x0']+w['x1'])/2,(w['top']+w['bottom'])/2))
                if t in('MH','TMH') and w['x0']<2150 and w['top']<1400:
                    cands=[v for v in W if re.match(r'^(\d+|FA)$',v['text']) and abs(v['x0']-w['x0'])<40 and abs(v['top']-w['top'])<40 and v is not w]
                    if cands:
                        v=cands[0]; wp.append(('MH '+v['text'],(w['x0']+w['x1'])/2,(w['top']+w['bottom'])/2))
            # dedupe labels
            seen={};[seen.setdefault(l,(x,y)) for l,x,y in wp]
            if not seen: continue
            rx=statistics.mean(v[0] for v in seen.values()); ry=statistics.mean(v[1] for v in seen.values())
            dev=[];dims=[]
            for w in W:
                if w['x0']>2150 or w['top']>1400: continue  # skip legend/title block/notes
                h=w['bottom']-w['top']; t=w['text']
                cx=(w['x0']+w['x1'])/2; cy=(w['top']+w['bottom'])/2
                if CODE.match(t) and h<10:
                    dev.append({'code':t,'dx_ft':round((cx-rx)/ppf,1),'dy_ft':round((cy-ry)/ppf,1)})
                elif DIM.match(t):
                    dims.append({'label':t,'dx_ft':round((cx-rx)/ppf,1),'dy_ft':round((cy-ry)/ppf,1)})
            big=sorted({w['text'] for w in W if CODE.match(w['text']) and (w['bottom']-w['top'])>=10 and w['x0']<2150})
            sheets.append({'page':i+1,'phase':phase,'scale':f'1\" = {scale_ft}\'','work_points':sorted(seen),
              'reference_point':'mean of work-point label centres','devices_at_posts':sorted(dev,key=lambda d:(d['dy_ft']>0,d['dx_ft'])),
              'dimension_labels':sorted(dims,key=lambda d:d['dx_ft']),'callout_codes':big,
              'arrow_board': 'FLASHING ARROW PANEL' in full,'notes_job_specific':[l.strip() for l in full.split('\n') if l.strip().startswith('- ')]})
        out[job]={'source_pdf':f.split('/')[-1],'expected_ta':ta,'sheets':sheets,'sheet_count':len(pdf.pages)}
json.dump(out,open('raw.json','w'),indent=1)
for job,v in out.items():
    print(job,v['sheet_count'])
    for s in v['sheets']:
        print(' ',s['phase'],s['scale'],s['work_points'],len(s['devices_at_posts']),'dims',len(s['dimension_labels']),s['callout_codes'])
