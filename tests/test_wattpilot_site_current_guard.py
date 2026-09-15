import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests import test_eco_pv_policy as eco_fixtures
from WattpilotSiteCurrentSource import SiteCurrentSnapshot


class WattpilotSiteCurrentGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        eco_fixtures.EcoPvPolicyRegressionTests.setUpClass()
        cls.fwp = eco_fixtures.EcoPvPolicyRegressionTests.fwp

    def _controller(self):
        fixture = eco_fixtures.EcoPvPolicyRegressionTests(
            methodName="test_one_phase_start_waits_for_the_stable_pv_timer"
        )
        fixture.fwp = self.fwp
        return fixture._controller()

    @staticmethod
    def _set_site(controller, l1, l2, l3, timestamp):
        for phase, value in zip(("L1", "L2", "L3"), (l1, l2, l3)):
            setattr(controller, "siteCurrent{0}Value".format(phase), value)
            setattr(controller, "siteCurrent{0}Valid".format(phase), True)
            setattr(controller, "siteCurrent{0}UpdatedAt".format(phase), timestamp)
        controller.wattpilot.energyTelemetryUpdatedAt = timestamp

    def _active_one_phase(self, controller, timestamp, amps=16):
        controller.currentPhaseMode = 1
        controller.wattpilot.modelStatus.value = 3
        controller.wattpilot.power = amps * 0.23
        controller.wattpilot.amp = amps
        controller.wattpilot.amps1 = amps
        controller.wattpilot.amps2 = 0
        controller.wattpilot.amps3 = 0
        controller.wattpilot.energyTelemetryUpdatedAt = timestamp

    def test_active_one_phase_is_reduced_to_physical_phase_headroom(self):
        controller = self._controller()
        self._active_one_phase(controller, 100, amps=16)
        # 27 A site current minus 16 A EV = 11 A house load, leaving 9 A.
        self._set_site(controller, 27, 4, 4, 100)
        controller.allowance = 5000
        controller.allowanceUpdatedAt = 100

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        controller.wattpilot.set_power.assert_called_once_with(9)
        controller.wattpilot.set_start_stop.assert_not_called()
        controller.wattpilot.set_phases.assert_not_called()

    def test_active_charge_stops_below_six_amp_headroom_without_phase_command(self):
        controller = self._controller()
        self._active_one_phase(controller, 100, amps=6)
        # 21 A total minus 6 A EV = 15 A house load, leaving only 5 A.
        self._set_site(controller, 21, 4, 4, 100)
        controller.publishServiceMessage = Mock()

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.StopCharging)
        controller.wattpilot.set_power.assert_called_once_with(0)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )
        controller.wattpilot.set_phases.assert_not_called()
        self.assertTrue(controller.siteCurrentGuardBlocked)
        self.assertIn("No phase headroom", controller.siteCurrentGuardReason)
        self.assertTrue(
            any(
                "Whole-site phase headroom is below" in call.args[1]
                for call in controller.publishServiceMessage.call_args_list
            )
        )

    def test_update_reuses_one_site_current_snapshot_for_active_charging(self):
        controller = self._controller()
        self._active_one_phase(controller, 100, amps=6)
        self._set_site(controller, 6, 0, 0, 100)
        controller.allowance = 1380
        controller.allowanceUpdatedAt = 100

        reads = []
        for phase, value in zip(("L1", "L2", "L3"), (6, 0, 0)):
            subscription = SimpleNamespace(value=value, phase=phase)
            setattr(controller, "siteCurrent{0}Dbus".format(phase), subscription)

        def read_once_per_phase(subscription):
            reads.append(subscription.phase)
            if len(reads) <= 3:
                return True, subscription.value
            return False, None

        controller.readDbusSubscription = Mock(side_effect=read_once_per_phase)

        with patch.object(self.fwp.time, "time", return_value=100):
            controller._update()

        self.assertEqual(reads, ["L1", "L2", "L3"])
        controller.wattpilot.set_start_stop.assert_not_called()

    def test_update_attributes_an_unsafe_first_site_current_snapshot(self):
        controller = self._controller()
        self._active_one_phase(controller, 100, amps=6)
        self._set_site(controller, 6, 0, 0, 100)
        controller.allowance = 1380
        controller.allowanceUpdatedAt = 100
        controller.publishServiceMessage = Mock()

        for phase, value in zip(("L1", "L2", "L3"), (6, 0, 0)):
            subscription = SimpleNamespace(value=value, phase=phase)
            setattr(controller, "siteCurrent{0}Dbus".format(phase), subscription)

        controller.readDbusSubscription = Mock(
            side_effect=lambda subscription: (
                (False, None)
                if subscription.phase == "L2"
                else (True, subscription.value)
            )
        )

        with patch.object(self.fwp.time, "time", return_value=100):
            controller._update()

        self.assertEqual(controller.readDbusSubscription.call_count, 3)
        controller.wattpilot.set_power.assert_called_once_with(0)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )
        controller.wattpilot.set_phases.assert_not_called()
        self.assertTrue(controller.siteCurrentGuardBlocked)
        self.assertIn("telemetry missing", controller.siteCurrentGuardReason)
        self.assertTrue(
            any(
                "Site-current telemetry is missing" in call.args[1]
                for call in controller.publishServiceMessage.call_args_list
            )
        )

    def test_expired_cycle_snapshot_fails_closed_without_a_second_read(self):
        controller = self._controller()
        self._active_one_phase(controller, 100, amps=6)
        self._set_site(controller, 6, 0, 0, 100)
        controller.publishServiceMessage = Mock()
        controller.refreshSiteCurrentGuard = Mock()
        snapshot = self.fwp.SiteCurrentGuardSnapshot(
            telemetry_fresh=True,
            limit_exceeded=False,
            evaluated_at=80,
        )

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging(snapshot)

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.StopCharging)
        controller.refreshSiteCurrentGuard.assert_not_called()
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )
        controller.wattpilot.set_phases.assert_not_called()
        self.assertIn("telemetry missing", controller.siteCurrentGuardReason)

    def test_stale_site_current_stops_even_when_grid_charging_and_assist_are_allowed(self):
        controller = self._controller()
        self._active_one_phase(controller, 100, amps=6)
        self._set_site(controller, 6, 0, 0, 70)
        controller.allowGridCharging = True
        controller.batteryAssistEnabled = True

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.StopCharging)
        controller.wattpilot.set_power.assert_called_once_with(0)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )

    def test_live_reads_refresh_unchanged_zero_and_nonzero_site_currents(self):
        controller = self._controller()
        self._set_site(controller, 0, 1.5, 0, 100)
        for phase, value in zip(("L1", "L2", "L3"), (0, 1.5, 0)):
            subscription = SimpleNamespace(value=value, phase=phase)
            setattr(controller, "siteCurrent{0}Dbus".format(phase), subscription)

        controller.readDbusSubscription = Mock(
            side_effect=lambda subscription: (True, subscription.value)
        )

        with patch.object(self.fwp.time, "time", return_value=200):
            controller.refreshSiteCurrentTelemetryHeartbeat()
            healthy = controller.siteCurrentTelemetryIsFresh(False)

        self.assertTrue(healthy)
        self.assertEqual(controller.siteCurrentL1Value, 0.0)
        self.assertEqual(controller.siteCurrentL2Value, 1.5)
        self.assertEqual(controller.siteCurrentL3Value, 0.0)
        self.assertEqual(controller.siteCurrentL1UpdatedAt, 200)
        self.assertEqual(controller.siteCurrentL2UpdatedAt, 200)
        self.assertEqual(controller.siteCurrentL3UpdatedAt, 200)
        self.assertEqual(controller.readDbusSubscription.call_count, 3)

    def test_failed_live_read_invalidates_phase_and_preserves_last_sample_age(self):
        controller = self._controller()
        self._set_site(controller, 2, 3, 4, 100)
        for phase, value in zip(("L1", "L2", "L3"), (2, 3, 4)):
            setattr(
                controller,
                "siteCurrent{0}Dbus".format(phase),
                SimpleNamespace(value=value, phase=phase),
            )

        controller.readDbusSubscription = Mock(
            side_effect=lambda subscription: (
                (False, None)
                if subscription.phase == "L3"
                else (True, subscription.value)
            )
        )

        with patch.object(self.fwp.time, "time", return_value=200):
            controller.refreshSiteCurrentTelemetryHeartbeat()
            healthy = controller.siteCurrentTelemetryIsFresh(False)

        self.assertFalse(healthy)
        self.assertTrue(controller.siteCurrentL1Valid)
        self.assertTrue(controller.siteCurrentL2Valid)
        self.assertFalse(controller.siteCurrentL3Valid)
        self.assertEqual(controller.siteCurrentL1UpdatedAt, 200)
        self.assertEqual(controller.siteCurrentL2UpdatedAt, 200)
        self.assertEqual(controller.siteCurrentL3UpdatedAt, 100)

    def test_successful_invalid_live_read_fails_closed(self):
        controller = self._controller()
        self._set_site(controller, 2, 3, 4, 100)
        for phase, value in zip(("L1", "L2", "L3"), (2, -1, 4)):
            setattr(
                controller,
                "siteCurrent{0}Dbus".format(phase),
                SimpleNamespace(value=value),
            )
        controller.readDbusSubscription = Mock(
            side_effect=lambda subscription: (True, subscription.value)
        )

        with patch.object(self.fwp.time, "time", return_value=200):
            controller.refreshSiteCurrentTelemetryHeartbeat()
            healthy = controller.siteCurrentTelemetryIsFresh(False)

        self.assertFalse(healthy)
        self.assertFalse(controller.siteCurrentL2Valid)
        self.assertEqual(controller.siteCurrentL2UpdatedAt, 200)

    def test_selected_provider_supplies_normalized_site_current_snapshot(self):
        controller = self._controller()
        controller.siteCurrentSource = Mock()
        controller.siteCurrentSource.read_sample.return_value = SiteCurrentSnapshot(
            source="Shelly3EMGen3",
            values={"L1": 1.0, "L2": 2.0, "L3": 3.0},
            valid={"L1": True, "L2": True, "L3": True},
            updated_at={"L1": 100.0, "L2": 100.0, "L3": 100.0},
            connected=True,
            status="Healthy",
            device_model="S3EM-003CXCEU63",
            firmware="1.7.0",
        )

        controller.refreshSiteCurrentTelemetryHeartbeat()

        self.assertEqual(controller.siteCurrentL1Value, 1.0)
        self.assertEqual(controller.siteCurrentL2Value, 2.0)
        self.assertEqual(controller.siteCurrentL3Value, 3.0)
        self.assertTrue(controller.siteCurrentSourceConnected)
        self.assertEqual(controller.siteCurrentSourceName, "Shelly3EMGen3")
        self.assertEqual(
            controller.siteCurrentSourceDeviceModel, "S3EM-003CXCEU63"
        )

    def test_selected_provider_failure_never_falls_back_to_venus_subscriptions(self):
        controller = self._controller()
        self._set_site(controller, 1, 2, 3, 50)
        controller.siteCurrentL1Dbus = SimpleNamespace(value=0)
        controller.siteCurrentL2Dbus = SimpleNamespace(value=0)
        controller.siteCurrentL3Dbus = SimpleNamespace(value=0)
        controller.readDbusSubscription = Mock(return_value=(True, 0))
        controller.siteCurrentSource = Mock()
        controller.siteCurrentSource.read_sample.return_value = SiteCurrentSnapshot(
            source="Shelly3EMGen3",
            values={"L1": 1.0, "L2": 2.0, "L3": 3.0},
            valid={"L1": False, "L2": False, "L3": False},
            updated_at={"L1": 50.0, "L2": 50.0, "L3": 50.0},
            connected=False,
            status="Unavailable",
            error="Shelly RPC request failed: Timeout",
        )

        controller.refreshSiteCurrentTelemetryHeartbeat()

        self.assertFalse(controller.siteCurrentL1Valid)
        self.assertFalse(controller.siteCurrentL2Valid)
        self.assertFalse(controller.siteCurrentL3Valid)
        self.assertEqual(controller.siteCurrentL1UpdatedAt, 50.0)
        controller.readDbusSubscription.assert_not_called()

    def test_shelly_poll_failure_withdraws_request_and_logs_transitions_only(self):
        controller = self._controller()
        controller.siteCurrentSourceName = "Shelly3EMGen3"
        controller.publishMainMqtt = Mock()
        controller.mqttRawOverheadW = 4800
        controller.mqttRawOverheadUpdatedAt = 110
        controller.wattpilot.power = 4.2
        failure = SiteCurrentSnapshot(
            source="Shelly3EMGen3",
            values={"L1": 6.0, "L2": 6.0, "L3": 6.0},
            valid={"L1": False, "L2": False, "L3": False},
            updated_at={"L1": 100.0, "L2": 100.0, "L3": 100.0},
            connected=False,
            status="Unavailable",
            error="Shelly RPC request failed: Timeout",
        )
        healthy = SiteCurrentSnapshot(
            source="Shelly3EMGen3",
            values={"L1": 6.0, "L2": 6.0, "L3": 6.0},
            valid={"L1": True, "L2": True, "L3": True},
            updated_at={"L1": 112.0, "L2": 112.0, "L3": 112.0},
            connected=True,
            status="Healthy",
        )
        controller.siteCurrentSource = Mock()
        controller.siteCurrentSource.poll.side_effect = (False, False, True)
        controller.siteCurrentSource.read_sample.side_effect = (
            failure,
            failure,
            healthy,
        )

        with patch.object(self.fwp, "w") as warning_log, patch.object(
            self.fwp, "i"
        ) as info_log:
            with patch.object(self.fwp.time, "time", return_value=110.0):
                self.assertFalse(controller.pollSiteCurrentSource())
            with patch.object(self.fwp.time, "time", return_value=111.0):
                self.assertFalse(controller.pollSiteCurrentSource())
            with patch.object(self.fwp.time, "time", return_value=112.0):
                self.assertTrue(controller.pollSiteCurrentSource())

        request_calls = [
            call
            for call in controller.publishMainMqtt.call_args_list
            if call.args[0].endswith("/Wattpilot/Request")
        ]
        self.assertEqual([call.args[1] for call in request_calls], [0, 0])
        warning_log.assert_called_once()
        info_log.assert_called_once()
        warning = warning_log.call_args.args[1]
        recovery = info_log.call_args.args[1]
        self.assertIn("reason=Shelly RPC request failed: Timeout", warning)
        self.assertIn("allocation_suppressed=true", warning)
        self.assertIn("positive_charger_command_authorized=false", warning)
        self.assertIn("site-current source recovered", recovery)
        self.assertNotIn("http://", warning)
        self.assertNotIn("password", warning.lower())
        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_start_stop.assert_not_called()

    def test_positive_request_waits_for_source_health_and_recovery(self):
        controller = self._controller()
        controller.siteCurrentSource = Mock()
        controller.siteCurrentSourceConnected = False
        controller.siteCurrentSourceStatus = "Unavailable"
        controller.siteCurrentGuardBlocked = True
        controller.publishMainMqtt = Mock()
        self._set_site(controller, 3, 3, 3, 100)

        with patch.object(self.fwp.time, "time", return_value=100.0):
            controller.reportBaseRequest()
        requests = [
            call.args[1]
            for call in controller.publishMainMqtt.call_args_list
            if call.args[0].endswith("/Wattpilot/Request")
        ]
        self.assertEqual(requests, [0])

        controller.publishMainMqtt.reset_mock()
        controller.siteCurrentSourceConnected = True
        controller.siteCurrentSourceStatus = "Healthy"
        controller.siteCurrentGuardBlocked = False
        controller.siteCurrentRecoverySince = {1: 105.0, 2: 105.0}
        self._set_site(controller, 3, 3, 3, 105)
        with patch.object(self.fwp.time, "time", return_value=105.0):
            controller.reportBaseRequest()
        requests = [
            call.args[1]
            for call in controller.publishMainMqtt.call_args_list
            if call.args[0].endswith("/Wattpilot/Request")
        ]
        self.assertEqual(requests, [0])

        controller.publishMainMqtt.reset_mock()
        self._set_site(controller, 3, 3, 3, 136)
        with patch.object(self.fwp.time, "time", return_value=136.0):
            controller.reportBaseRequest()
        requests = [
            call.args[1]
            for call in controller.publishMainMqtt.call_args_list
            if call.args[0].endswith("/Wattpilot/Request")
        ]
        self.assertEqual(len(requests), 1)
        self.assertGreater(requests[0], 0)

    def test_equal_active_current_allows_request_recovery_after_a_site_reduction(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.siteCurrentSource = Mock()
        controller.siteCurrentSourceConnected = True
        controller.siteCurrentSourceStatus = "Healthy"
        controller.siteCurrentRecoverySince = {1: 0, 2: 1}
        controller.publishMainMqtt = Mock()
        controller.wattpilot.modelStatus.value = 3
        controller.wattpilot.power = 7.0
        controller.wattpilot.amp = 10
        controller.wattpilot.amps1 = 10
        controller.wattpilot.amps2 = 10
        controller.wattpilot.amps3 = 10
        # Physical headroom allows only 9 A while Wattpilot still reports 10 A.
        self._set_site(controller, 21, 21, 21, 100)
        allowance = 9 * controller.allocationStepForPhase(2)

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertEqual(
                controller.safeTargetCurrentForPhase(2, allowance), 9
            )
        self.assertEqual(controller.siteCurrentRecoverySince[2], 0)

        controller.wattpilot.amp = 9
        controller.wattpilot.amps1 = 9
        controller.wattpilot.amps2 = 9
        controller.wattpilot.amps3 = 9
        self._set_site(controller, 20, 20, 20, 105)
        with patch.object(self.fwp.time, "time", return_value=105):
            controller.updateSiteCurrentRecovery(
                2, controller.siteCurrentDecision(2, True), now=105
            )
            self.assertEqual(
                controller.safeTargetCurrentForPhase(2, allowance), 9
            )
            controller.reportBaseRequest()

        request_calls = [
            call.args[1]
            for call in controller.publishMainMqtt.call_args_list
            if call.args[0].endswith("/Wattpilot/Request")
        ]
        self.assertEqual(request_calls, [0])
        self.assertEqual(controller.siteCurrentRecoverySince[2], 105)

        controller.publishMainMqtt.reset_mock()
        self._set_site(controller, 20, 20, 20, 135)
        with patch.object(self.fwp.time, "time", return_value=135):
            controller.updateSiteCurrentRecovery(
                2, controller.siteCurrentDecision(2, True), now=135
            )
            self.assertEqual(
                controller.safeTargetCurrentForPhase(2, allowance), 9
            )
            controller.reportBaseRequest()

        request_calls = [
            call.args[1]
            for call in controller.publishMainMqtt.call_args_list
            if call.args[0].endswith("/Wattpilot/Request")
        ]
        self.assertEqual(len(request_calls), 1)
        self.assertGreater(request_calls[0], 0)
        self.assertEqual(controller.siteCurrentRecoverySince[2], 105)

    def test_pv_reduction_keeps_positive_request_with_safe_site_headroom(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.siteCurrentSource = Mock()
        controller.siteCurrentSourceConnected = True
        controller.siteCurrentSourceStatus = "Healthy"
        controller.siteCurrentGuardBlocked = False
        controller.siteCurrentRecoverySince = {1: 1, 2: 60}
        controller.publishMainMqtt = Mock()
        controller.wattpilot.modelStatus.value = 3
        controller.wattpilot.power = 7.0
        controller.wattpilot.amp = 10
        controller.wattpilot.amps1 = 10
        controller.wattpilot.amps2 = 10
        controller.wattpilot.amps3 = 10
        self._set_site(controller, 10, 10, 10, 100)
        allowance = 9 * controller.allocationStepForPhase(2)

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertEqual(
                controller.safeTargetCurrentForPhase(2, allowance), 9
            )
            self.assertTrue(controller.allowWattpilotCommand("amp", 9))
            controller.reportBaseRequest()

        self.assertEqual(controller.siteCurrentRecoverySince[2], 60)
        requests = [
            call.args[1]
            for call in controller.publishMainMqtt.call_args_list
            if call.args[0].endswith("/Wattpilot/Request")
        ]
        self.assertEqual(len(requests), 1)
        self.assertGreater(requests[0], 0)

    def test_disconnected_idle_refresh_publishes_latest_shelly_snapshot_only(self):
        controller = self._controller()
        controller.mode = self.fwp.VrmEvChargerControlMode.Auto
        controller.currentPhaseMode = 1
        controller.siteCurrentSource = Mock()
        controller.siteCurrentRecoverySince = {1: 25.0, 2: 30.0}
        controller.phaseSwitchCandidateMode = 2
        controller.phaseSwitchCandidateSince = 40.0
        retained = {}
        controller.publishRetained = retained.__setitem__

        controller.siteCurrentSource.read_sample.side_effect = (
            SiteCurrentSnapshot(
                source="Shelly3EMGen3",
                values={"L1": 3.5, "L2": 6.0, "L3": 0.5},
                valid={"L1": True, "L2": True, "L3": True},
                updated_at={"L1": 100.0, "L2": 100.0, "L3": 100.0},
                connected=True,
                status="Healthy",
                device_model="S3EM-003CXCEU63",
                firmware="2.0.0",
            ),
            SiteCurrentSnapshot(
                source="Shelly3EMGen3",
                values={"L1": 3.3, "L2": 0.4, "L3": 0.5},
                valid={"L1": True, "L2": True, "L3": True},
                updated_at={"L1": 105.0, "L2": 105.0, "L3": 105.0},
                connected=True,
                status="Healthy",
                device_model="S3EM-003CXCEU63",
                firmware="2.0.0",
            ),
            SiteCurrentSnapshot(
                source="Shelly3EMGen3",
                values={"L1": 3.3, "L2": 0.4, "L3": 0.5},
                valid={"L1": False, "L2": False, "L3": False},
                updated_at={"L1": 105.0, "L2": 105.0, "L3": 105.0},
                connected=False,
                status="Unavailable",
                error="Shelly RPC request failed: Timeout",
                device_model="S3EM-003CXCEU63",
                firmware="2.0.0",
            ),
        )

        with patch.object(self.fwp.time, "time", return_value=100.0):
            controller.refreshIdleSiteCurrentDiagnostics()

        self.assertEqual(retained["/SiteCurrentL1"], 3.5)
        self.assertEqual(retained["/SiteCurrentL2"], 6.0)
        self.assertEqual(retained["/SiteCurrentL3"], 0.5)
        self.assertEqual(retained["/SiteCurrentSourceLastSampleAge"], 0.0)
        self.assertEqual(retained["/SiteCurrentTelemetryHealthy"], 1)
        self.assertEqual(retained["/SiteAllowedCurrent"], 16)
        self.assertEqual(retained["/SiteLimitingPhase"], "L1")
        self.assertEqual(retained["/SiteCurrentGuardBlocked"], 0)

        with patch.object(self.fwp.time, "time", return_value=105.0):
            controller.refreshIdleSiteCurrentDiagnostics()

        self.assertEqual(retained["/SiteCurrentL1"], 3.3)
        self.assertEqual(retained["/SiteCurrentL2"], 0.4)
        self.assertEqual(retained["/SiteCurrentL3"], 0.5)
        self.assertEqual(retained["/SiteCurrentSourceLastSampleAge"], 0.0)
        self.assertEqual(retained["/SiteCurrentTelemetryHealthy"], 1)

        with patch.object(self.fwp.time, "time", return_value=110.0):
            controller.refreshIdleSiteCurrentDiagnostics()

        self.assertEqual(retained["/SiteCurrentL2"], 0.4)
        self.assertEqual(retained["/SiteCurrentSourceConnected"], 0)
        self.assertEqual(retained["/SiteCurrentSourceStatus"], "Unavailable")
        self.assertEqual(retained["/SiteCurrentSourceLastSampleAge"], 5.0)
        self.assertEqual(retained["/SiteCurrentAgeL2"], 5.0)
        self.assertEqual(retained["/SiteCurrentTelemetryHealthy"], 0)
        self.assertEqual(retained["/SiteCurrentGuardBlocked"], 1)
        self.assertIn("telemetry missing", retained["/SiteCurrentGuardReason"])
        self.assertEqual(controller.siteCurrentRecoverySince, {1: 25.0, 2: 30.0})
        self.assertEqual(controller.phaseSwitchCandidateMode, 2)
        self.assertEqual(controller.phaseSwitchCandidateSince, 40.0)
        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_start_stop.assert_not_called()

    def test_shelly_selection_registers_no_consumption_or_grid_meter_source(self):
        controller = self._controller()
        controller.siteCurrentSourceName = "Shelly3EMGen3"
        controller.config["Shelly3EMSiteCurrent"] = {
            "Host": "192.0.2.40",
            "Username": "admin",
            "Password": "secret",
            "PollFrequencyMs": "1000",
            "RequestTimeoutSeconds": "2",
            "PhaseA": "L3",
            "PhaseB": "L1",
            "PhaseC": "L2",
        }
        subscriptions = []

        def register(service_name, dbus_path, **_kwargs):
            subscriptions.append((service_name, dbus_path))
            return SimpleNamespace(value=None)

        controller.registerDbusSubscription = Mock(side_effect=register)
        client = Mock()
        source = Mock()

        with patch.object(
            self.fwp, "Shelly3EMGen3Client", return_value=client
        ) as client_class, patch.object(
            self.fwp, "Shelly3EMSiteCurrentSource", return_value=source
        ) as source_class:
            controller.initDbusSubscriptions()

        self.assertIs(controller.siteCurrentSource, source)
        self.assertFalse(
            any(path.startswith("/Ac/Consumption/") for _service, path in subscriptions)
        )
        self.assertFalse(
            any(service == "com.victronenergy.grid" for service, _path in subscriptions)
        )
        client_class.assert_called_once_with(
            host="192.0.2.40",
            username="admin",
            password="secret",
            timeout_seconds=2.0,
        )
        source_class.assert_called_once_with(
            client=client,
            phase_mapping={"A": "L3", "B": "L1", "C": "L2"},
            poll_frequency_ms=1000,
            transient_failure_grace_seconds=0,
        )

    def test_transient_shelly_grace_blocks_risky_commands_but_allows_reduction(self):
        controller = self._controller()
        self._active_one_phase(controller, 100, amps=8)
        self._set_site(controller, 8, 0, 0, 100)
        controller.siteCurrentSourceName = "Shelly3EMGen3"
        controller.siteCurrentSourceConnected = False
        controller.siteCurrentSourceStatus = "Degraded"
        controller.siteCurrentSourceLastSampleAt = 100
        controller.siteCurrentTransientFailureGraceSeconds = 5
        controller.siteCurrentRecoverySince = {1: 1, 2: 1}

        with patch.object(self.fwp.time, "time", return_value=102):
            snapshot = controller.refreshSiteCurrentGuard()
            self.assertTrue(snapshot.telemetry_fresh)
            self.assertTrue(controller.siteCurrentGuardBlocked)
            self.assertEqual(controller.siteCurrentRecoverySince, {1: 0, 2: 0})
            self.assertTrue(controller.allowWattpilotCommand("amp", 7))
            self.assertTrue(controller.allowWattpilotCommand("amp", 8))
            self.assertFalse(controller.allowWattpilotCommand("amp", 9))
            self.assertFalse(controller.allowWattpilotCommand("psm", 2))
            self.assertFalse(
                controller.allowWattpilotCommand(
                    "frc", self.fwp.WattpilotStartStop.On
                )
            )
            self.assertTrue(controller.allowWattpilotCommand("amp", 0))
            self.assertTrue(
                controller.allowWattpilotCommand(
                    "frc", self.fwp.WattpilotStartStop.Off
                )
            )

    def test_transient_shelly_grace_allows_active_phase_down_only(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.wattpilot.modelStatus.value = 3
        controller.wattpilot.power = 5.5
        controller.wattpilot.amp = 8
        controller.wattpilot.amps1 = 8
        controller.wattpilot.amps2 = 8
        controller.wattpilot.amps3 = 8
        controller.wattpilot.energyTelemetryUpdatedAt = 100
        self._set_site(controller, 8, 8, 8, 100)
        controller.siteCurrentSourceName = "Shelly3EMGen3"
        controller.siteCurrentSourceStatus = "Degraded"
        controller.siteCurrentSourceLastSampleAt = 100
        controller.siteCurrentTransientFailureGraceSeconds = 5

        with patch.object(self.fwp.time, "time", return_value=102):
            self.assertTrue(controller.allowWattpilotCommand("psm", 1))
            self.assertFalse(controller.allowWattpilotCommand("psm", 2))

    def test_expired_transient_shelly_grace_blocks_positive_commands(self):
        controller = self._controller()
        self._active_one_phase(controller, 100, amps=8)
        self._set_site(controller, 8, 0, 0, 100)
        controller.siteCurrentSource = Mock()
        controller.siteCurrentSource.read_sample.return_value = SiteCurrentSnapshot(
            source="Shelly3EMGen3",
            values={"L1": 8.0, "L2": 0.0, "L3": 0.0},
            valid={"L1": True, "L2": True, "L3": True},
            updated_at={"L1": 100.0, "L2": 100.0, "L3": 100.0},
            connected=False,
            status="Degraded",
            error="Shelly RPC request failed: Timeout",
        )
        controller.siteCurrentTransientFailureGraceSeconds = 5

        with patch.object(self.fwp.time, "time", return_value=106):
            snapshot = controller.refreshSiteCurrentGuard()
            self.assertFalse(snapshot.telemetry_fresh)
            self.assertFalse(controller.allowWattpilotCommand("amp", 7))
            self.assertTrue(controller.allowWattpilotCommand("amp", 0))

    def test_source_cleanup_failure_cannot_interrupt_auto_shutdown_stop(self):
        controller = self._controller()
        events = []
        controller.wattpilot = Mock()
        controller.wattpilot.connected = True
        controller.wattpilot.set_start_stop.side_effect = (
            lambda _state: events.append("stop")
        )
        controller.wattpilot.disconnect.side_effect = (
            lambda: events.append("disconnect")
        )
        controller.siteCurrentSource = Mock()

        def fail_cleanup():
            events.append("source-close")
            raise RuntimeError("cleanup failed")

        controller.siteCurrentSource.close.side_effect = fail_cleanup

        controller.handleSigterm()

        self.assertEqual(events, ["stop", "disconnect", "source-close"])
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )

    def test_disconnect_failure_cannot_skip_site_source_cleanup(self):
        controller = self._controller()
        events = []
        controller.wattpilot = Mock()
        controller.wattpilot.connected = False

        def fail_disconnect():
            events.append("disconnect")
            raise RuntimeError("synthetic disconnect failure")

        controller.wattpilot.disconnect.side_effect = fail_disconnect
        controller.siteCurrentSource = Mock()
        controller.siteCurrentSource.close.side_effect = (
            lambda: events.append("source-close")
        )

        with patch.object(self.fwp, "w") as warning_log:
            controller.handleSigterm()

        self.assertEqual(events, ["disconnect", "source-close"])
        warning_log.assert_called_once()
        self.assertIn(
            "Wattpilot cleanup failed during shutdown: RuntimeError.",
            warning_log.call_args.args[1],
        )

    def test_three_phase_start_falls_back_to_one_phase_when_another_phase_is_full(self):
        controller = self._controller()
        controller.allowance = 5000
        controller.allowanceUpdatedAt = 100
        self._set_site(controller, 0, 15.5, 0, 100)
        controller.siteCurrentRecoverySince = {1: 1, 2: 1}

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.startFromPvAllowance()

        self.assertEqual(controller.currentPhaseMode, 1)
        controller.wattpilot.set_phases.assert_called_once_with(1)
        controller.wattpilot.set_power.assert_called_once_with(16)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.On
        )

    def test_start_is_blocked_when_mapped_one_phase_and_three_phase_are_below_minimum(self):
        controller = self._controller()
        controller.allowance = 5000
        controller.allowanceUpdatedAt = 100
        self._set_site(controller, 15.5, 0, 0, 100)
        controller.siteCurrentRecoverySince = {1: 1, 2: 1}

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.startFromPvAllowance()

        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_start_stop.assert_not_called()

    def test_three_phase_current_uses_one_common_smallest_headroom(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.wattpilot.modelStatus.value = 3
        controller.wattpilot.amp = 8
        controller.wattpilot.amps1 = 8
        controller.wattpilot.amps2 = 8
        controller.wattpilot.amps3 = 8
        self._set_site(controller, 19, 14, 12, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            decision = controller.siteCurrentDecision(2, True)

        self.assertEqual(decision.headrooms, (9, 14, 16))
        self.assertEqual(decision.allowed_current, 9)
        self.assertEqual(decision.limiting_phase, "L1")

    def test_phase_switch_waits_for_fresh_current_telemetry_after_reduction(self):
        controller = self._controller()
        self._active_one_phase(controller, 100, amps=16)
        self._set_site(controller, 27, 4, 4, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            first = controller.commandSiteSafePhaseTransition(2, 9)

        self.assertEqual(first, "reducing")
        controller.wattpilot.set_power.assert_called_once_with(9)
        controller.wattpilot.set_phases.assert_not_called()

        controller.wattpilot.amp = 9
        with patch.object(self.fwp.time, "time", return_value=105):
            waiting = controller.commandSiteSafePhaseTransition(2, 9)

        self.assertEqual(waiting, "reducing")
        controller.wattpilot.set_phases.assert_not_called()

        controller.wattpilot.energyTelemetryUpdatedAt = 106
        controller.wattpilot.amps1 = 9
        with patch.object(self.fwp.time, "time", return_value=110):
            switched = controller.commandSiteSafePhaseTransition(2, 9)

        self.assertEqual(switched, "switched")
        controller.wattpilot.set_phases.assert_called_once_with(2)

    def test_rejected_phase_command_does_not_mutate_controller_phase_state(self):
        controller = self._controller()
        controller.currentPhaseMode = 1
        controller.wattpilot.amp = 6
        controller.wattpilot.set_phases.return_value = False

        result = controller.commandSiteSafePhaseTransition(2, 6)

        self.assertFalse(result)
        self.assertEqual(controller.currentPhaseMode, 1)
        controller.wattpilot.set_phases.assert_called_once_with(2)
        controller.wattpilot.set_power.assert_not_called()

    def test_final_command_boundary_fails_closed_but_allows_stop_commands(self):
        controller = self._controller()
        controller.siteCurrentL1Valid = False

        self.assertFalse(controller.allowWattpilotCommand("amp", 6))
        self.assertFalse(controller.allowWattpilotCommand("psm", 2))
        self.assertFalse(
            controller.allowWattpilotCommand(
                "frc", self.fwp.WattpilotStartStop.On
            )
        )
        self.assertTrue(controller.allowWattpilotCommand("amp", 0))
        self.assertTrue(
            controller.allowWattpilotCommand(
                "frc", self.fwp.WattpilotStartStop.Off
            )
        )

    def test_equal_current_final_guard_preserves_pending_recovery_timer(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.wattpilot.modelStatus.value = 3
        controller.wattpilot.power = 5.0
        controller.wattpilot.amp = 7
        controller.wattpilot.amps1 = 7
        controller.wattpilot.amps2 = 7
        controller.wattpilot.amps3 = 7
        self._set_site(controller, 7, 7, 7, 100)
        controller.siteCurrentRecoverySince = {1: 0, 2: 0}

        with patch.object(self.fwp.time, "time", return_value=100):
            held_current = controller.siteLimitedTargetCurrent(2, 9)
            self.assertEqual(held_current, 7)
            self.assertEqual(controller.siteCurrentRecoverySince[2], 100)
            self.assertTrue(
                controller.allowWattpilotCommand("amp", held_current)
            )

        self.assertEqual(controller.siteCurrentRecoverySince[2], 100)

        self._set_site(controller, 7, 7, 7, 129)
        with patch.object(self.fwp.time, "time", return_value=129):
            self.assertEqual(controller.siteLimitedTargetCurrent(2, 9), 7)

        self._set_site(controller, 7, 7, 7, 130)
        with patch.object(self.fwp.time, "time", return_value=130):
            self.assertEqual(controller.siteLimitedTargetCurrent(2, 9), 8)

    def test_equal_current_final_guard_still_enforces_lower_site_headroom(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.wattpilot.modelStatus.value = 3
        controller.wattpilot.power = 5.0
        controller.wattpilot.amp = 7
        controller.wattpilot.amps1 = 7
        controller.wattpilot.amps2 = 7
        controller.wattpilot.amps3 = 7
        # Removing the 7 A EV contribution leaves 14 A of non-EV load and
        # therefore only 6 A of site-safe charger headroom.
        self._set_site(controller, 21, 21, 21, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertFalse(controller.allowWattpilotCommand("amp", 7))

    def test_stopped_lower_setpoint_preserves_recovery_before_start(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.wattpilot.modelStatus.value = 4
        controller.wattpilot.power = 0
        controller.wattpilot.amp = 16
        self._set_site(controller, 0, 0, 0, 100)
        controller.siteCurrentRecoverySince = {1: 1, 2: 1}

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertTrue(controller.siteCurrentRecoveryReady(2))
            self.assertTrue(controller.allowWattpilotCommand("psm", 2))
            self.assertTrue(controller.allowWattpilotCommand("amp", 6))
            self.assertEqual(controller.siteCurrentRecoverySince[2], 1)
            self.assertTrue(
                controller.allowWattpilotCommand(
                    "frc",
                    int(
                        getattr(
                            self.fwp.WattpilotStartStop.On,
                            "value",
                            self.fwp.WattpilotStartStop.On,
                        )
                    ),
                )
            )

    def test_stopped_setpoint_still_waits_for_site_recovery(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.wattpilot.modelStatus.value = 4
        controller.wattpilot.power = 0
        controller.wattpilot.amp = 16
        self._set_site(controller, 0, 0, 0, 100)
        controller.siteCurrentRecoverySince = {1: 0, 2: 100}

        with patch.object(self.fwp.time, "time", return_value=120):
            self.assertFalse(controller.allowWattpilotCommand("amp", 6))
            self.assertFalse(
                controller.allowWattpilotCommand(
                    "frc",
                    int(
                        getattr(
                            self.fwp.WattpilotStartStop.On,
                            "value",
                            self.fwp.WattpilotStartStop.On,
                        )
                    ),
                )
            )

    def test_auto_start_with_retained_higher_setpoint_reaches_start_command(self):
        controller = self._controller()
        controller.allowance = 4200
        controller.allowanceUpdatedAt = 100
        controller.surplusSince = 1
        controller.wattpilot.amp = 16
        self._set_site(controller, 0, 0, 0, 100)
        controller.siteCurrentRecoverySince = {1: 1, 2: 1}
        controller.wattpilot.set_phases.side_effect = (
            lambda value: controller.allowWattpilotCommand("psm", value)
        )
        controller.wattpilot.set_power.side_effect = (
            lambda value: controller.allowWattpilotCommand("amp", value)
        )
        controller.wattpilot.set_start_stop.side_effect = (
            lambda value: controller.allowWattpilotCommand(
                "frc", int(getattr(value, "value", value))
            )
        )

        with patch.object(self.fwp.time, "time", return_value=100):
            started = controller.startFromPvAllowance()

        self.assertTrue(started)
        controller.wattpilot.set_phases.assert_called_once_with(2)
        controller.wattpilot.set_power.assert_called_once_with(6)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.On
        )
        self.assertGreater(controller.powerTransitionUntil, 100)
        self.assertEqual(
            controller.dbusService["/StartStop"],
            self.fwp.VrmEvChargerStartStop.Start.value,
        )

    def test_auto_start_accepts_guarded_current_noop_before_start(self):
        controller = self._controller()
        controller.allowance = 4200
        controller.allowanceUpdatedAt = 100
        controller.surplusSince = 1
        controller.wattpilot.connected = True
        controller.wattpilot.amp = 6
        controller.wattpilot.ampUpdatedAt = 100
        self._set_site(controller, 0, 0, 0, 100)
        controller.siteCurrentRecoverySince = {1: 1, 2: 1}
        controller.wattpilot.set_phases.side_effect = (
            lambda value: controller.allowWattpilotCommand("psm", value)
        )
        controller.wattpilot.set_start_stop.side_effect = (
            lambda value: controller.allowWattpilotCommand(
                "frc", int(getattr(value, "value", value))
            )
        )

        with patch.object(self.fwp.time, "time", return_value=100):
            started = controller.startFromPvAllowance()

        self.assertTrue(started)
        controller.wattpilot.set_phases.assert_called_once_with(2)
        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.On
        )

    def test_rejected_guarded_current_noop_aborts_start_transaction(self):
        controller = self._controller()
        controller.allowance = 4200
        controller.allowanceUpdatedAt = 100
        controller.surplusSince = 1
        controller.wattpilot.connected = True
        controller.wattpilot.amp = 6
        controller.wattpilot.ampUpdatedAt = 100
        self._set_site(controller, 0, 0, 0, 100)
        controller.siteCurrentRecoverySince = {1: 1, 2: 1}

        def accept_phase_then_remove_headroom(value):
            accepted = controller.allowWattpilotCommand("psm", value)
            self._set_site(controller, 15, 15, 15, 100)
            return accepted

        controller.wattpilot.set_phases.side_effect = accept_phase_then_remove_headroom

        with patch.object(self.fwp.time, "time", return_value=100):
            started = controller.startFromPvAllowance()

        self.assertFalse(started)
        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_start_stop.assert_not_called()

    def test_rejected_auto_start_does_not_publish_false_transition_state(self):
        controller = self._controller()
        controller.allowance = 4200
        controller.allowanceUpdatedAt = 100
        controller.surplusSince = 1
        controller.lastOnOffTime = 0
        self._set_site(controller, 0, 0, 0, 100)
        controller.siteCurrentRecoverySince = {1: 1, 2: 1}
        controller.wattpilot.set_phases.return_value = True
        controller.wattpilot.set_power.return_value = True
        controller.wattpilot.set_start_stop.return_value = False

        with patch.object(self.fwp.time, "time", return_value=100):
            started = controller.startFromPvAllowance()

        self.assertFalse(started)
        self.assertEqual(controller.powerTransitionUntil, 0)
        self.assertEqual(controller.lastOnOffTime, 0)
        self.assertEqual(controller.surplusSince, 0)
        self.assertEqual(
            controller.dbusService["/StartStop"],
            self.fwp.VrmEvChargerStartStop.Stop.value,
        )
        self.assertEqual(
            controller.dbusService["/StartStopLiteral"],
            self.fwp.VrmEvChargerStartStop.Stop.name,
        )

    def test_rejected_phase_or_current_aborts_the_remaining_start_sequence(self):
        for rejected_stage in ("phase", "current"):
            with self.subTest(rejected_stage=rejected_stage):
                controller = self._controller()
                controller.allowance = 4200
                controller.allowanceUpdatedAt = 100
                controller.surplusSince = 1
                controller.lastOnOffTime = 0
                self._set_site(controller, 0, 0, 0, 100)
                controller.siteCurrentRecoverySince = {1: 1, 2: 1}
                controller.wattpilot.set_phases.return_value = (
                    rejected_stage != "phase"
                )
                controller.wattpilot.set_power.return_value = (
                    rejected_stage != "current"
                )

                with patch.object(self.fwp.time, "time", return_value=100):
                    started = controller.startFromPvAllowance()

                self.assertFalse(started)
                self.assertEqual(controller.powerTransitionUntil, 0)
                self.assertEqual(controller.lastOnOffTime, 0)
                self.assertEqual(controller.surplusSince, 0)
                controller.wattpilot.set_start_stop.assert_not_called()
                if rejected_stage == "phase":
                    controller.wattpilot.set_power.assert_not_called()
                    self.assertEqual(controller.currentPhaseMode, 1)
                else:
                    controller.wattpilot.set_power.assert_called_once_with(6)


if __name__ == "__main__":
    unittest.main()
