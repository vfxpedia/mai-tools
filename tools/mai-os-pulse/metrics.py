"""Pure metric transforms; unavailable readings remain None."""
import math

def numeric(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None

def rate(current, previous, elapsed):
    if current is None or previous is None or elapsed <= 0:
        return None
    return max(0, current - previous) / elapsed

def observations(snapshot):
    hints = []
    cores = snapshot.get('cores', [])
    if cores and max(cores) >= 90 and sum(cores)/len(cores) < 50:
        hints.append('일부 논리 프로세서 포화 · 단일 스레드/전처리 흐름 확인')
    ram = snapshot.get('ram', {})
    if ram.get('total') and ram.get('available', 0)/ram['total'] < .1:
        hints.append('RAM 여유 10% 미만 · 배치 크기와 데이터 캐시 확인')
    for gpu in snapshot.get('gpus', []):
        if gpu.get('total') and gpu.get('used') is not None and gpu['used']/gpu['total'] > .9:
            hints.append(f"GPU {gpu['index']} VRAM 90% 초과 · 배치/모델 배치 확인")
    if not hints:
        hints.append('임계치 관찰 없음 · 성능 정상 판정은 아님')
    return hints
