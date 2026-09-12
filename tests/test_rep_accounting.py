"""Historical representative costs and private resale notes, using a temporary DB."""
import sys
import io
import zipfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import database as db, rep_accounting as accounting
from core.rep_report import build_rep_report, rep_report_xlsx

class AccountingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='atlas-accounting-')
        self.addCleanup(self.tmp.cleanup)
        path=str(Path(self.tmp.name)/'test.db')
        for mod in (db, accounting):
            p=patch.object(mod,'DB_PATH',path);p.start();self.addCleanup(p.stop)
        await db.init_db()
        self.rep=await db.get_or_create_user(1001,'rep','Rep')
        await db.update_user(self.rep['id'],is_wholesale=1)
        self.rep=await db.get_user_by_id(self.rep['id'])
        self.other=await db.get_or_create_user(1002,'other','Other')
        await db.update_user(self.other['id'],is_wholesale=1)
        self.pkg=await db.add_package('Plan',30,7,100000)

    async def purchase(self,price=None,bulk=1):
        if bulk>1:
            oid=await db.create_custom_order(self.rep['id'],'Bulk',30*bulk,7,price,bulk_count=bulk,bulk_each_gb=30,package_id=self.pkg)
        else:
            oid=await db.create_order(self.rep['id'],self.pkg,custom_price=price or 0)
        await db.update_order(oid,status='approved')
        pids=[]
        for i in range(bulk):
            pids.append(await db.create_subscription_profile(self.rep['id'],oid,f'tok-{oid}-{i}',f'email-{oid}-{i}',30,7,0))
        return oid,pids

    async def test_snapshot_and_actual_wallet_cost_survive_repricing(self):
        oid,pids=await self.purchase()
        await db.update_package(self.pkg,price=900000,traffic_gb=500,duration_days=90)
        order=await db.get_order(oid)
        self.assertEqual((order['price'],order['traffic_gb'],order['duration_days']),(100000,30,7))
        report=await build_rep_report(self.rep,preset='all',include_sales=True)
        self.assertEqual(report['rows'][0]['price'],100000)
        await db.add_user_balance(self.rep['id'],-87500,kind='purchase',note=f'order:{oid}')
        await accounting.set_sale_price(self.rep['id'],'purchase',oid,pids[0],150000)
        report=await build_rep_report(self.rep,preset='all',include_sales=True)
        self.assertEqual(report['rows'][0]['price'],87500)
        self.assertEqual(report['summary']['total_profit'],62500)
        self.assertEqual((await db.get_rep_financials(self.rep['id']))['total_spent'],87500)
        self.assertEqual(report['summary']['total_revenue'],150000)
        self.assertEqual(await db.get_user_balance(self.rep['id']),-87500)
        private_free=await build_rep_report(self.rep,preset='all')
        self.assertNotIn('sale_price',private_free['rows'][0])
        self.assertNotIn('total_profit',private_free['summary'])
        with zipfile.ZipFile(io.BytesIO(rep_report_xlsx(report))) as book:
            sheet = book.read('xl/worksheets/sheet1.xml').decode('utf-8')
            self.assertIn('قیمت فروش (تومان)', sheet)
            self.assertIn('<v>150000</v>', sheet)
            self.assertIn('<v>62500</v>', sheet)
        with zipfile.ZipFile(io.BytesIO(rep_report_xlsx(private_free))) as book:
            self.assertNotIn('قیمت فروش (تومان)', book.read('xl/worksheets/sheet1.xml').decode('utf-8'))

    async def test_bulk_renewal_zero_missing_and_range_totals(self):
        oid,pids=await self.purchase(10000,3)
        renew=await db.create_custom_order(self.rep['id'],'Renew',0,0,4000,package_id=self.pkg)
        await db.update_order(renew,status='approved',renew_sub_profile_id=pids[0])
        self.assertEqual((await db.get_order(renew))['traffic_gb'],0)
        await accounting.set_sale_price(self.rep['id'],'purchase',oid,pids[0],5000)
        await accounting.set_sale_price(self.rep['id'],'purchase',oid,pids[1],0)
        await accounting.set_sale_price(self.rep['id'],'renewal',renew,0,8000)
        report=await build_rep_report(self.rep,preset='all',include_sales=True)
        self.assertEqual(sum(r['price'] for r in report['rows']),14000)
        self.assertEqual(report['summary']['total_revenue'],13000)
        self.assertEqual(report['summary']['total_profit'],2333)
        self.assertEqual(report['summary']['unpriced_count'],1)
        limited=await build_rep_report(self.rep,preset='all',limit=1,include_sales=True)
        self.assertEqual(len(limited['rows']),1)
        self.assertEqual(limited['summary']['total_revenue'],13000)
        await accounting.set_sale_price(self.rep['id'],'purchase',oid,pids[0],None)
        report=await build_rep_report(self.rep,preset='all',include_sales=True)
        self.assertEqual(report['summary']['unpriced_count'],2)
        empty=await build_rep_report(self.rep,date_from='1390/01/01',date_to='1390/01/02',include_sales=True)
        self.assertEqual(empty['summary']['total_revenue'],0)

    async def test_refunds_are_removed_from_historical_cost(self):
        oid,pids=await self.purchase(60000,2)
        await db.add_user_balance(self.rep['id'],-60000,kind='purchase',note=f'order:{oid}')
        await db.add_user_balance(self.rep['id'],60000,kind='refund',note=f'order_failed:{oid}')
        await db.add_user_balance(self.rep['id'],-60000,kind='purchase',note=f'order:{oid}')
        await db.add_user_balance(self.rep['id'],30000,kind='refund',note=f'order_partial:{oid}')
        await db.update_order(oid,custom_price=30000)
        report=await build_rep_report(self.rep,preset='all',include_sales=True)
        self.assertEqual(report['summary']['total_spent'],30000)
        self.assertEqual(sum(r['price'] for r in report['rows']),30000)
        await db.init_db()  # additive migration remains safe across restarts
        self.assertEqual((await db.get_order(oid))['traffic_gb'],60)

    async def test_unknown_old_price_and_isolation(self):
        oid,pids=await self.purchase()
        await db.update_order(oid,price_snapshot=None)
        await db.update_package(self.pkg,price=999000)
        self.assertFalse(await accounting.set_sale_price(self.other['id'],'purchase',oid,pids[0],200000))
        for price in [-1,1.5,True,'1000',10**14]:
            with self.assertRaises(ValueError):
                await accounting.set_sale_price(self.rep['id'],'purchase',oid,pids[0],price)
        await accounting.set_sale_price(self.rep['id'],'purchase',oid,pids[0],200000)
        report=await build_rep_report(self.rep,preset='all',include_sales=True)
        self.assertIsNone(report['rows'][0]['price'])
        self.assertIsNone(report['rows'][0]['profit'])
        self.assertEqual(report['summary']['unknown_cost_orders'],1)
        self.assertEqual(report['summary']['unknown_sale_cost_count'],1)
        self.assertEqual(report['summary']['total_profit'],0)
        await db.update_user(self.rep['id'],is_wholesale=0)
        self.assertFalse(await accounting.set_sale_price(self.rep['id'],'purchase',oid,pids[0],250000))

    async def test_endpoint_auth_and_payload(self):
        from web import app as web
        import httpx
        oid,pids=await self.purchase()
        body={'kind':'purchase','order_id':oid,'profile_id':pids[0],'sale_price':150000}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),base_url='http://test') as client:
            with patch.object(web,'get_setting',AsyncMock(return_value='1')),patch.object(web,'_miniapp_user',AsyncMock(return_value=self.rep)):
                self.assertEqual((await client.post('/app/api/rep/purchases/sale-price',json=body)).status_code,200)
                self.assertEqual((await client.post('/app/api/rep/purchases/sale-price',json={**body,'sale_price':-1})).status_code,400)
                self.assertEqual((await client.post('/app/api/rep/purchases/sale-price',json={**body,'order_id':999999})).status_code,403)
            with patch.object(web,'get_setting',AsyncMock(return_value='1')),patch.object(web,'_miniapp_user',AsyncMock(return_value=None)):
                self.assertEqual((await client.post('/app/api/rep/purchases/sale-price',json=body)).status_code,401)

if __name__=='__main__': unittest.main()
