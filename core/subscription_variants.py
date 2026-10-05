"""Admin-visible switches for variants sharing one quota-bearing client."""
import asyncio,json,re
from core.database import get_setting,set_setting

OPTION_KEYS=('subscription_ws_early_data','subscription_ws_fallbacks','subscription_ws_ech',
             'subscription_ws_no_ed','subscription_ws_backups','subscription_ws_hide_regular',
             'subscription_ws_disabled_variants')
PROTECTED_TARGETS=('4:3','6:2')
_switch_lock=asyncio.Lock()

async def load_variant_options():
    options={}
    for key in OPTION_KEYS:
        try:
            value=json.loads(await get_setting(key,'{}'))
            options[key]=value if isinstance(value,dict) else {}
        except (TypeError,ValueError):options[key]={}
    return options

def variant_enabled(options,target,kind):
    if target in PROTECTED_TARGETS:return True
    if kind=='regular' and options.get('subscription_ws_hide_regular',{}).get(target) is True:return False
    disabled=options.get('subscription_ws_disabled_variants',{}).get(target,[])
    return not (isinstance(disabled,list) and kind in disabled)

def describe_variants(options,target,address=''):
    if target in PROTECTED_TARGETS:return []
    if not any(target in options.get(k,{}) for k in OPTION_KEYS if k!='subscription_ws_disabled_variants'):return []
    rows=[dict(id='regular',label='معمولی',address=address)]
    fallback=options.get('subscription_ws_fallbacks',{}).get(target)
    if not isinstance(fallback,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}',fallback):fallback=None
    if fallback:rows.append(dict(id='fallback',label='Backup',address=fallback))
    ech=options.get('subscription_ws_ech',{}).get(target,{})
    if isinstance(ech,dict):
        if ech.get('primary'):rows.append(dict(id='plus',label='Plus',address=address))
        if fallback and ech.get('backup'):rows.append(dict(id='plus-backup',label='Plus Backup',address=fallback))
    if options.get('subscription_ws_no_ed',{}).get(target) is True:
        rows.append(dict(id='mobin',label='Mobin WS',address=address))
        if fallback:rows.append(dict(id='mobin-backup',label='Mobin WS Backup',address=fallback))
    backups=options.get('subscription_ws_backups',{}).get(target,[])
    if isinstance(backups,list):
        for index,backup in enumerate(backups[:3]):
            if not isinstance(backup,dict):continue
            rows.append(dict(id=f'backup-{index}',label='Backup M' if backup.get('no_ed') and not backup.get('ech') else f'Backup {index+1}',address=backup.get('address','')))
    for row in rows:row['is_active']=variant_enabled(options,target,row['id'])
    return rows

async def toggle_variant(target,kind):
    async with _switch_lock:
        return await _toggle_variant(target,kind)

async def _toggle_variant(target,kind):
    if target in PROTECTED_TARGETS:raise ValueError('protected_target')
    options=await load_variant_options()
    rows=describe_variants(options,target)
    row=next((r for r in rows if r['id']==kind),None)
    if not row:raise ValueError('unknown_variant')
    enabled=not row['is_active']
    if kind=='regular':
        hidden=options['subscription_ws_hide_regular'];hidden[target]=not enabled
        await set_setting('subscription_ws_hide_regular',json.dumps(hidden))
    else:
        switches=options['subscription_ws_disabled_variants']
        previous=switches.get(target,[]);disabled=set(previous if isinstance(previous,list) else [])
        if enabled:disabled.discard(kind)
        else:disabled.add(kind)
        switches[target]=sorted(disabled)
        await set_setting('subscription_ws_disabled_variants',json.dumps(switches))
    return enabled
