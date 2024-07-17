"""A small server to mock the FinWorks API for testing purposes."""

from aiohttp import web
import json
import os
import logging
import ipdb
import pkg_resources

# Get module-named logger.
logger = logging.getLogger(__name__)

# Path to test JSON test fixture files
TEST_FIXTURES_PATH = pkg_resources.resource_filename('tests', 'fixtures/finworks')

async def load_json(file_path):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"No such file: '{file_path}'")
    with open(file_path, 'r') as f:
        data = json.load(f)
    return data

async def handle_model_portfolios(request):
    try:
        file_path = os.path.join(TEST_FIXTURES_PATH, 'models.json')
        data = await load_json(file_path)
        data = {"size": len(data), "data": data}
        return web.json_response(data)
    except Exception as e:
        logging.error(f"Error in handle_model_portfolios: {e}")
        return web.Response(status=500, text="Internal server error")

async def handle_instruments(request):
    try:
        file_path = os.path.join(TEST_FIXTURES_PATH, 'instruments.json')
        data = await load_json(file_path)
        data = {"size": len(data), "data": data}
        return web.json_response(data)
    except Exception as e:
        logging.error(f"Error in handle_instruments: {e}")
        return web.Response(status=500, text="Internal server error")

async def handle_investors(request):
    try:
        file_path = os.path.join(TEST_FIXTURES_PATH, 'investors.json')
        data = await load_json(file_path)
        data = {"size": len(data), "data": data}
        return web.json_response(data)
    except Exception as e:
        logging.error(f"Error in handle_investors: {e}")
        return web.Response(status=500, text="Internal server error")

async def handle_holdings(request):
    try:
        date = request.rel_url.query.get('date')
        if not date:
            return web.Response(status=400, text="Missing 'date' parameter")
        file_path = os.path.join(TEST_FIXTURES_PATH, f'holdings-{date}.json')
        data = await load_json(file_path)
        data = {"size": len(data), "data": data}
        return web.json_response(data)
    except Exception as e:
        logging.error(f"Error in handle_holdings: {e}")
        return web.Response(status=500, text="Internal server error")

async def handle_transactions(request):
    try:
        date = request.rel_url.query.get('date')
        if not date:
            return web.Response(status=400, text="Missing 'date' parameter")
        file_path = os.path.join(TEST_FIXTURES_PATH, f'transactions-{date}.json')
        data = await load_json(file_path)
        data = {"size": len(data), "data": data}
        return web.json_response(data)
    except Exception as e:
        logging.error(f"Error in handle_transactions: {e}")
        return web.Response(status=500, text="Internal server error")

def create_server():
    app = web.Application()
    app.router.add_get('/api/modelmanager/model-portfolios', handle_model_portfolios)
    app.router.add_get('/api/modelmanager/instruments', handle_instruments)
    app.router.add_get('/api/modelmanager/investors', handle_investors)
    app.router.add_get('/api/modelmanager/holdings', handle_holdings)
    app.router.add_get('/api/modelmanager/transactions', handle_transactions)
    return app

