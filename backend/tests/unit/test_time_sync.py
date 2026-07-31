import time

import pytest

from cryptobot.exchange.errors import ClockDriftError
from cryptobot.exchange.time_sync import TimeSync


class TestTimeSync:
    def test_unsynced_raises(self):
        with pytest.raises(ClockDriftError, match="never synchronized"):
            TimeSync().timestamp_ms()

    def test_synced_timestamp_close_to_server_time(self):
        ts = TimeSync()
        server_now_ms = int(time.time() * 1000) + 200  # server 200ms ahead
        ts.update(server_now_ms)
        assert abs(ts.timestamp_ms() - (time.time() * 1000 + 200)) < 50

    def test_excess_drift_fails_closed(self):
        ts = TimeSync(max_drift_ms=1000)
        ts.update(int(time.time() * 1000) + 5000)  # 5s drift
        with pytest.raises(ClockDriftError, match="drift"):
            ts.timestamp_ms()

    def test_is_synced_reflects_recency(self):
        ts = TimeSync()
        assert not ts.is_synced
        ts.update(int(time.time() * 1000))
        assert ts.is_synced
