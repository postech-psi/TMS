"""Regression checks for data loss and plausible-looking invalid measurements."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import tms_data_pipeline as pipeline


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, text):
        p = self.root / name
        p.write_text(text)
        return p

    def test_header_does_not_consume_first_sensor_pair(self):
        p = self.write('record.txt', '1000000\n500000\n-4942\n32767\n-4945\n32767\n')
        r = pipeline.load_recording(p)
        np.testing.assert_array_equal(r['loadcell_adc'], [-4942, -4945])
        self.assertEqual(r['sampling_start_us'], 1000000)

    def test_startup_probe_is_not_a_timed_recording(self):
        p = self.write('probe.txt', '-4953\n32767\n')
        with self.assertRaisesRegex(ValueError, 'startup-only'):
            pipeline.load_recording(p)

    def test_incomplete_pair_is_rejected(self):
        p = self.write('odd.txt', '1000000\n500000\n-4942\n32767\n-4945\n')
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            pipeline.load_recording(p)

    def test_invalid_adc_is_rejected(self):
        p = self.write('bad.txt', '1000000\n500000\n-4942\n32768\n')
        with self.assertRaisesRegex(ValueError, '16-bit'):
            pipeline.load_recording(p)

    def test_idle_noise_cannot_become_a_fifteen_second_burn(self):
        a = -4945 + np.tile([-1, 0, 1, 0], 1200)
        q = pipeline.assess_channels(a, np.full(a.size, 32767))
        self.assertFalse(q['event_detected'])
        self.assertEqual(q['thrust_status'], 'no_event')

    def test_saturated_pressure_is_missing_and_raw_adc_is_preserved(self):
        adc = np.full(1600, -4937)
        adc[500:1000] -= 400
        lines = ['1000000', '500000']
        for value in adc:
            lines.extend([str(value), '32767'])
        p = self.write('event.txt', '\n'.join(lines) + '\n')
        with patch.multiple(pipeline, INPUT_FILE=p, INPUT_FILENAME=p.name,
                            OUTPUT_DIR=self.root, OUTPUT_PREFIX='test', GENERATE_PLOTS=False):
            result = pipeline.main()
        self.assertTrue(result['quality']['event_detected'])
        self.assertIsNone(result['pressure']['peak_pressure'])
        data = np.genfromtxt(self.root / 'test_pipeline_data.txt', names=True, delimiter='\t')
        self.assertTrue(np.isnan(data['filtered_gauge_pressure']).all())
        np.testing.assert_array_equal(data['loadcell_adc'], adc)
        self.assertTrue((data['pressure_adc'] == 32767).all())
        self.assertNotIn('Peak pressure: 0.000', (self.root / 'test_executive_report.txt').read_text())

    def test_decay_fit_excludes_false_tail_and_integrates_fractional_endpoint(self):
        time = np.arange(4800) / 320
        force = np.where(time < 2, 0., np.where(time < 3, 100., np.maximum(0., 100 * (4-time))))
        force[time >= 3.8] = 20.
        original = force.copy()
        legacy = pipeline.calculate_thrust_metrics(time, force)
        result = pipeline.calculate_thrust_metrics(time, force, burnout_fit_window=(3.3, 3.7))
        self.assertEqual(legacy['burnout_time'], time[-1])
        self.assertAlmostEqual(result['burnout_time'], 3.97, places=10)
        self.assertAlmostEqual(result['burn_time'], 1.97, places=10)
        self.assertAlmostEqual(result['total_impulse'], 149.955, places=8)
        self.assertAlmostEqual(result['avg_thrust'], 149.955 / 1.97, places=8)
        self.assertAlmostEqual(result['tail_extrapolation']['zero_crossing_s'], 4., places=10)
        np.testing.assert_array_equal(force, original)
        analysis = pipeline.apply_burnout_tail(time, force, result['tail_extrapolation'])
        np.testing.assert_array_equal(analysis[time < 3.7], original[time < 3.7])
        self.assertTrue((analysis[time >= 4] == 0).all())

    def test_flat_tail_cannot_be_used_as_a_decay_fit(self):
        time = np.arange(1600) / 320
        force = np.where((time >= 1) & (time < 2), 100., 20.)
        with self.assertRaisesRegex(ValueError, 'descending line'):
            pipeline.calculate_thrust_metrics(time, force, burnout_fit_window=(3., 3.5))

    def test_decay_fit_must_follow_peak(self):
        time = np.arange(1600) / 320
        force = np.where((time >= 1) & (time < 2), 100., 0.)
        with self.assertRaisesRegex(ValueError, 'follow peak'):
            pipeline.calculate_thrust_metrics(time, force, burnout_fit_window=(.1, .5))


if __name__ == '__main__':
    unittest.main()
