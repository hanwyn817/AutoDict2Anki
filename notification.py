import logging
import re
import requests
import config

logger = logging.getLogger(__name__)

def sc_send(title: str, desp: str = '') -> None:
    sendkey = config.SERVERCHAN_SENDKEY
    if not sendkey:
        return

    try:
        # 判断 sendkey 是否以 'sctp' 开头，并提取数字构造 URL
        if sendkey.startswith('sctp'):
            match = re.match(r'sctp(\d+)t', sendkey)
            if match:
                num = match.group(1)
                url = f'https://{num}.push.ft07.com/send/{sendkey}.send'
            else:
                logger.error('Invalid sendkey format for sctp')
                return
        else:
            url = f'https://sctapi.ftqq.com/{sendkey}.send'

        params = {'title': title, 'desp': desp}
        headers = {'Content-Type': 'application/json;charset=utf-8'}
        
        response = requests.post(url, json=params, headers=headers, timeout=10)
        response.raise_for_status()
        result = response.json()
        logger.info(f"Server酱推送结果: {result}")
    except Exception as e:
        logger.error(f"Server酱推送异常: {e}")
