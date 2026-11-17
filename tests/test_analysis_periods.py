import unittest
from unittest.mock import patch

import app
import detector


class NormalizeAnalysisPeriodsTests(unittest.TestCase):
    def test_empty_periods_keeps_full_video_analysis(self):
        self.assertEqual(
            app.normalize_analysis_periods([], 125.5),
            [{"start": 0.0, "end": 125.5}],
        )

    def test_periods_are_sorted_merged_and_limited_to_video(self):
        self.assertEqual(
            app.normalize_analysis_periods(
                [{"start": 50, "end": 150}, {"start": 10, "end": 55}, {"start": 70, "end": 80}],
                100,
            ),
            [{"start": 10.0, "end": 100.0}],
        )

    def test_invalid_period_is_rejected(self):
        with self.assertRaises(ValueError):
            app.normalize_analysis_periods([{"start": 12, "end": 12}], 100)


class SuggestPeriodsTests(unittest.TestCase):
    def test_close_periods_are_never_merged_across_an_unselected_gap(self):
        first = [{"t": index * 0.5, "people": [], "green_x": None} for index in range(10)]
        second = [{"t": 6 + index * 0.5, "people": [], "green_x": None} for index in range(10)]

        with patch.object(detector, "light_threshold", return_value=100), patch.object(
            detector, "label_samples", side_effect=lambda samples, *args, **kwargs: [detector.ATAQUE] * len(samples)
        ):
            result = detector.suggest_periods([(5.0, first), (11.0, second)], mine_is_light=True)

        self.assertEqual(result[detector.ATAQUE], [{"start": 0.0, "end": 5.0}, {"start": 6.0, "end": 11.0}])


if __name__ == "__main__":
    unittest.main()
