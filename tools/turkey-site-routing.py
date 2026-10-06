"""Install scoped TLS fragmentation in the Turkey 3x-ui template over SSH.

Uses the panel's persisted template and sniffing settings, never subscription
links. Backups remain private on the target; rollback restores only these fields.
"""

import argparse
import json
import subprocess

REMOTE = r'''
import copy,json,os,sqlite3,subprocess,tempfile,time
from pathlib import Path

DB='/etc/x-ui/x-ui.db'
CONFIG=Path('/usr/local/x-ui/bin/config.json')
BIN='/usr/local/x-ui/bin/xray-linux-amd64'
TAG='atlas-tr-site-fragment'
DOMAINS=['domain:pornhub.com','domain:pornhub.org','domain:phncdn.com','domain:phprcdn.com']
FRAGMENT={'packets':'tlshello','length':'5','interval':'0'}
SNIFF={'enabled':True,'destOverride':['http','tls'],'metadataOnly':False,'routeOnly':True}
env=dict(os.environ,XRAY_LOCATION_ASSET='/usr/local/x-ui/bin')

def command(args):
 p=subprocess.run(args,capture_output=True,text=True,timeout=30)
 if p.returncode:raise RuntimeError(args[0]+' failed: '+p.stderr[-220:])
 return p.stdout

def validate(cfg):
 with tempfile.TemporaryDirectory(prefix='atlas-tr-validate-') as tmp:
  path=Path(tmp)/'config.json';path.write_text(json.dumps(cfg));path.chmod(0o600)
  p=subprocess.run([BIN,'run','-test','-c',str(path)],env=env,capture_output=True,text=True,timeout=15)
  if p.returncode:raise RuntimeError('Xray rejected candidate: '+p.stderr[-220:])

def state():
 with sqlite3.connect(DB) as db:
  return {'template':db.execute("SELECT value FROM settings WHERE key='xrayTemplateConfig'").fetchone()[0],
          'sniffing':[[r[0],r[1]] for r in db.execute('SELECT id,sniffing FROM inbounds WHERE enable=1 AND (node_id IS NULL OR node_id=0)')]}

def client_contract():
 with sqlite3.connect(DB) as db:
  return {table:sorted(db.execute(query).fetchall(),key=repr) for table,query in [
   ('clients','SELECT * FROM clients'),
   ('client_inbounds','SELECT * FROM client_inbounds'),
   ('inbounds','SELECT id,settings,stream_settings,listen,port,protocol,enable,expiry_time,total,allocate FROM inbounds')]}

def without_generated_clients(cfg):
 # The panel updates clients through the live API without rewriting config.json.
 # A restart regenerates those lists from the unchanged panel database.
 cfg=copy.deepcopy(cfg)
 for inbound in cfg.get('inbounds',[]):
  inbound.get('settings',{}).pop('clients',None)
 return cfg

def write_fields(value):
 with sqlite3.connect(DB,timeout=10) as db:
  assert db.execute("UPDATE settings SET value=? WHERE key='xrayTemplateConfig'",(value['template'],)).rowcount==1
  for iid,sniff in value['sniffing']:
   assert db.execute('UPDATE inbounds SET sniffing=? WHERE id=?',(sniff,iid)).rowcount==1

def start():
 command(['systemctl','start','x-ui'])
 for _ in range(40):
  p=subprocess.run(['pgrep','-f','^bin/xray-linux-amd64 -c bin/config.json$'],capture_output=True)
  if p.returncode==0:
   time.sleep(.5);return
  time.sleep(.25)
 raise RuntimeError('production Xray did not start')

if mode=='rollback':
 path=Path(backup).resolve()
 root=Path('/root/atlas-backups').resolve()
 assert path.parent==root and path.name.startswith('turkey-site-routing-'),'invalid backup location'
 original=json.loads((path/'original-fields.json').read_text())
 current=state()
 expected=json.loads((path/'applied-fields.json').read_text())
 assert current==expected,'panel changed since deployment; refusing to overwrite newer settings'
 command(['systemctl','stop','x-ui'])
 try:write_fields(original);start()
 except Exception:
  write_fields(current);start();raise
 print(json.dumps({'rollback':'OK','backup':str(path)}));raise SystemExit(0)

original=state()
original_clients=client_contract()
template=json.loads(original['template'])
existing=[o for o in template.get('outbounds',[]) if o.get('tag')==TAG]
rule={'type':'field','domain':DOMAINS,'network':'tcp','port':'80,443','outboundTag':TAG}
outbound={'tag':TAG,'protocol':'freedom','settings':{'fragment':FRAGMENT}}
if existing:
 assert existing==[outbound] and rule in template['routing']['rules'],'conflicting existing scoped route'
 assert all(json.loads(v)==SNIFF for _,v in original['sniffing']),'existing route has different sniffing settings'
 runtime=json.loads(CONFIG.read_text())
 assert outbound in runtime['outbounds'] and rule in runtime['routing']['rules'],'persisted route is not present in runtime config'
 validate(runtime)
 print(json.dumps({'already_applied':True}));raise SystemExit(0)
assert original['sniffing'],'no active local inbounds'
assert template['outbounds'][0]['tag']=='direct','unexpected default outbound'
assert all(not json.loads(v or '{}').get('enabled') for _,v in original['sniffing']),'review existing sniffing before changing it'
candidate=copy.deepcopy(template)
candidate['outbounds'].append(outbound)
candidate['routing']['rules'].append(rule)
runtime=json.loads(CONFIG.read_text())
expected_runtime=copy.deepcopy(runtime)
expected_runtime['outbounds'].append(outbound)
expected_runtime['routing']['rules'].append(rule)
for i in expected_runtime['inbounds']:
 if i.get('protocol')!='dokodemo-door':i['sniffing']=SNIFF
validate(expected_runtime)
print(json.dumps({'candidate_valid':True,'domains':DOMAINS,'fragment':FRAGMENT,'active_inbounds':len(original['sniffing'])}),flush=True)
if mode=='check':raise SystemExit(0)

root=Path('/root/atlas-backups');root.mkdir(mode=0o700,exist_ok=True)
path=root/('turkey-site-routing-'+time.strftime('%Y%m%d-%H%M%S'));path.mkdir(mode=0o700)
with sqlite3.connect(DB) as db,sqlite3.connect(str(path/'x-ui.db')) as saved:db.backup(saved)
(path/'runtime-before.json').write_text(json.dumps(runtime))
(path/'original-fields.json').write_text(json.dumps(original))
updated={'template':json.dumps(candidate),'sniffing':[[iid,json.dumps(SNIFF)] for iid,_ in original['sniffing']]}
(path/'applied-fields.json').write_text(json.dumps(updated))
for file in path.iterdir():file.chmod(0o600)
command(['systemctl','stop','x-ui'])
try:
 assert state()==original,'panel settings changed before deployment'
 write_fields(updated)
 start()
 actual=json.loads(CONFIG.read_text())
 assert without_generated_clients(actual)==without_generated_clients(expected_runtime),'runtime changed outside the expected outbound, routing, and sniffing fields'
 assert client_contract()==original_clients,'persisted client identities, assignments, quotas, or transports changed'
 validate(actual)
 assert state()==updated,'persisted settings mismatch'
except Exception:
 command(['systemctl','stop','x-ui']);write_fields(original);start();raise
print(json.dumps({'applied':'OK','backup':str(path),'inbound_clients_and_transports_unchanged':True}),flush=True)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-host', default='atlas')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--apply', action='store_true')
    actions.add_argument('--rollback', metavar='REMOTE_BACKUP_DIRECTORY')
    args = parser.parse_args()
    mode = 'rollback' if args.rollback else 'apply' if args.apply else 'check'
    code = 'mode=' + repr(mode) + '\nbackup=' + repr(args.rollback) + '\n' + REMOTE
    result = subprocess.run(
        ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', args.ssh_host, 'python3 -'],
        input=code, text=True, encoding='utf-8', capture_output=True, timeout=90,
    )
    print(result.stdout, end='')
    if result.returncode:
        print(result.stderr[-1000:])
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
