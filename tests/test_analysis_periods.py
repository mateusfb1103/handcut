import unittest
from collections import deque
from unittest.mock import MagicMock, patch

import numpy as np

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

    def test_goal_sides_is_isolated_per_period(self):
        # Período 1: 12 quadros com gol à esquerda (green_x=0.1).
        # Período 2: 2 quadros iniciais com gol à direita (green_x=0.9), mas time claro perto da direita (DEFESA se gol=direita, ATAQUE se gol=esquerda).
        # Se goal_sides vazasse do Período 1 para o Período 2, a mediana ainda seria < 0.5 (gol à esquerda) e inverteria os primeiros quadros.
        light_left = [(0.15, 0.6, 220.0), (0.18, 0.65, 220.0), (0.20, 0.7, 220.0)]
        dark_right = [(0.80, 0.6, 30.0), (0.82, 0.65, 30.0), (0.85, 0.7, 30.0)]
        light_right = [(0.80, 0.6, 220.0), (0.82, 0.65, 220.0), (0.85, 0.7, 220.0)]
        dark_left = [(0.15, 0.6, 30.0), (0.18, 0.65, 30.0), (0.20, 0.7, 30.0)]

        p1 = [{"t": i * 0.5, "people": light_left + dark_right, "green_x": 0.1} for i in range(14)]
        p2 = [{"t": 20.0 + i * 0.5, "people": light_right + dark_left, "green_x": 0.9} for i in range(10)]

        # Ambos os períodos têm o time claro defendendo (perto do respectivo gol):
        # Período 1 perto de x=0.08 (esquerda) e Período 2 perto de x=0.92 (direita).
        result = detector.suggest_periods([(7.0, p1), (25.0, p2)], mine_is_light=True)
        self.assertEqual(result[detector.ATAQUE], [])
        self.assertEqual(len(result[detector.DEFESA]), 2)
        self.assertEqual(result[detector.DEFESA][1]["start"], 20.0)

    def test_goal_sides_new_features_isolated_per_period(self):
        # Garante isolamento do novo caminho (cov_diff/end_score) entre períodos vizinhos.
        light_left = [(0.15, 0.6, 220.0), (0.18, 0.65, 220.0), (0.20, 0.7, 220.0)]
        dark_right = [(0.80, 0.6, 30.0), (0.82, 0.65, 30.0), (0.85, 0.7, 30.0)]
        light_right = [(0.80, 0.6, 220.0), (0.82, 0.65, 220.0), (0.85, 0.7, 220.0)]
        dark_left = [(0.15, 0.6, 30.0), (0.18, 0.65, 30.0), (0.20, 0.7, 30.0)]

        p1 = [{"t": i * 0.5, "people": light_left + dark_right, "cov_diff": -0.02, "end_score": -0.8} for i in range(14)]
        p2 = [{"t": 20.0 + i * 0.5, "people": light_right + dark_left, "cov_diff": 0.02, "end_score": 0.8} for i in range(10)]
        result = detector.suggest_periods([(7.0, p1), (25.0, p2)], mine_is_light=True)
        self.assertEqual(result[detector.ATAQUE], [])
        self.assertEqual(len(result[detector.DEFESA]), 2)
        self.assertEqual(result[detector.DEFESA][1]["start"], 20.0)

    def test_court_side_features_detects_non_green_blue_court_endlines(self):
        # Quadra sintética azul (sem verde) com linha de fundo à direita (\) e parede cinza atrás.
        from collections import deque
        import numpy as np
        import cv2

        frame = np.full((240, 426, 3), (90, 90, 90), dtype=np.uint8)
        poly = np.array([[0, 75], [220, 75], [425, 145], [425, 239], [0, 239]])
        cv2.fillPoly(frame, [poly], (190, 120, 30))  # piso azul em BGR
        cv2.line(frame, (220, 75), (425, 145), (0, 230, 230), 2)  # linha de fundo direita (\)
        history = deque(maxlen=30)
        cov_diff, end_score = detector._court_side_features(frame, history)
        self.assertIsNotNone(end_score)
        self.assertGreater(end_score, 0.0)


class DetectorTimeAndEdgesTests(unittest.TestCase):
    def test_read_frames_preserves_absolute_time_offset(self):
        frame_bytes = 854 * 480 * 3
        fake_stdout = MagicMock()
        fake_stdout.read.side_effect = [b"\x00" * frame_bytes, b"\x00" * frame_bytes, b"\x00" * frame_bytes, b""]
        fake_proc = MagicMock(stdout=fake_stdout)

        with patch("detector.subprocess.Popen", return_value=fake_proc):
            frames = list(detector.read_frames(app.ROOT / "video.mp4", 300.0, 1280, 720, fps=2.0, start=120.5, end=123.0))

        self.assertEqual([t for t, _ in frames], [120.5, 121.0, 121.5])

    def test_light_threshold_uses_fallback_below_50_observations(self):
        few = [{"t": 0.0, "people": [(0.5, 0.5, 220.0)] * 49, "green_x": 0.1}]
        self.assertEqual(detector.light_threshold(few), 100.0)

        enough = [{"t": 0.0,
                   "people": [(0.5, 0.5, float(v)) for v in range(20, 45)] + [(0.5, 0.5, float(v)) for v in range(195, 220)],
                   "green_x": 0.1}]
        thresh = detector.light_threshold(enough)
        self.assertGreaterEqual(thresh, 44.0)
        self.assertLess(thresh, 195.0)
        self.assertNotEqual(thresh, 100.0)

    def test_border_voting_and_min_segment_seconds(self):
        # 6 quadros = 3.0 s (< MIN_SEGMENT_SECONDS=4.0) -> descartado
        samples = [{"t": i * 0.5, "people": [(0.85, 0.6, 220.0)] * 3 + [(0.15, 0.6, 30.0)] * 3, "green_x": 0.1}
                   for i in range(6)]
        labels = detector.label_samples(samples, mine_is_light=True, threshold=120.0)
        self.assertEqual(labels, [detector.ATAQUE] * 6)
        self.assertEqual(detector.labels_to_segments(samples, labels, detector.ATAQUE), [])

    def test_labels_to_segments_requires_min_active_duration_and_merges_brief_dropouts(self):
        # Dois ruídos curtos (1.0 s + 1.5 s = 2.5 s ativos) separados por 2.0 s de defesa:
        # duração externa seria 4.5 s, mas o tempo ativo (< 4.0 s) deve ser descartado.
        noise_labels = [detector.ATAQUE] * 2 + [detector.DEFESA] * 4 + [detector.ATAQUE] * 3
        noise_samples = [{"t": i * 0.5} for i in range(len(noise_labels))]
        self.assertEqual(detector.labels_to_segments(noise_samples, noise_labels, detector.ATAQUE), [])

        # Lance contínuo de 6.0 s ativos com queda breve de 2.5 s no meio deve virar 1 único lance.
        play_labels = [detector.ATAQUE] * 6 + [detector.DEFESA] * 5 + [detector.ATAQUE] * 6
        play_samples = [{"t": i * 0.5} for i in range(len(play_labels))]
        segs = detector.labels_to_segments(play_samples, play_labels, detector.ATAQUE)
        self.assertEqual(segs, [{"start": 0.0, "end": 8.5}])

    def test_yolox_grid_and_decode_filters_person_scales_and_applies_nms(self):
        grids, strides = detector._build_yolox_grids(640, 640)
        self.assertEqual(grids.shape, (8400, 2))
        self.assertEqual(strides.shape, (8400, 1))

        # Constrói saída sintética (8400, 85):
        # - âncora 0 (stride=8, grid=(0,0)): pessoa forte em cx=16, cy=24, w=16, h=32 (na escala 640)
        # - âncora 1 (stride=8, grid=(1,0)): caixa quase sobreposta com score menor (deve sumir no NMS)
        # - âncora 2: outra classe (cls=1) com confiança alta e person=0.05 (deve ser descartada)
        out = np.zeros((8400, 85), dtype=np.float32)
        out[0, :4] = [2.0, 3.0, np.log(2.0), np.log(4.0)]
        out[0, 4] = 0.90
        out[0, 5 + detector.PERSON_CLASS] = 0.80  # score = 0.72

        out[1, :4] = [1.1, 3.0, np.log(2.0), np.log(4.0)]
        out[1, 4] = 0.60
        out[1, 5 + detector.PERSON_CLASS] = 0.60  # score = 0.36 (sobrepõe âncora 0 -> NMS)

        out[2, :4] = [10.0, 10.0, np.log(3.0), np.log(3.0)]
        out[2, 4] = 0.95
        out[2, 5 + detector.PERSON_CLASS] = 0.05  # score pessoa = 0.0475 < 0.25
        out[2, 6] = 0.99                          # outra classe

        # ratio=0.5 -> dobra coordenadas na volta ao quadro original 1280x720
        dets = detector._decode_yolox(out, grids, strides, ratio=0.5, frame_width=1280, frame_height=720, conf_min=0.25)
        self.assertEqual(dets.shape, (1, 5))
        # cx=16, cy=24, w=16, h=32 -> [8, 8, 24, 40] / 0.5 = [16, 16, 48, 80]
        np.testing.assert_allclose(dets[0, :4], [16.0, 16.0, 48.0, 80.0], atol=1e-3)
        self.assertAlmostEqual(float(dets[0, 4]), 0.72, places=3)

        self.assertEqual(detector.MODEL_FILE.name, "yolox_s.onnx")
        self.assertTrue((detector.MODEL_FILE.parent / "LICENSE-YOLOX.txt").is_file())
        self.assertTrue((detector.MODEL_FILE.parent / "NOTICE").is_file())


class TeamColorSeparationTests(unittest.TestCase):
    def test_separates_same_luminance_yellow_vs_red_and_black_vs_blue_in_lab(self):
        # Mesmo brilho L=125: amarelo (a=120, b=185) vs vermelho (a=185, b=150)
        yellow = (0.80, 0.60, 125.0, 120.0, 185.0)
        red = (0.20, 0.60, 125.0, 185.0, 150.0)
        samples = [{"t": i * 0.5, "people": [yellow] * 3 + [red] * 3, "cov_diff": 0.0, "end_score": 0.8}
                   for i in range(10)]
        proto = detector.team_prototypes(samples, shirt="amarela")
        self.assertTrue(detector.classify_person(yellow, proto))
        self.assertFalse(detector.classify_person(red, proto))

        # Mesmo brilho baixo L=55: preto neutro (a=128, b=128) vs azul (a=130, b=78)
        black = (0.20, 0.60, 55.0, 128.0, 128.0)
        blue = (0.80, 0.60, 55.0, 130.0, 78.0)
        samples_bb = [{"t": i * 0.5, "people": [black] * 3 + [blue] * 3, "cov_diff": 0.0, "end_score": 0.8}
                      for i in range(10)]
        proto_blue = detector.team_prototypes(samples_bb, shirt="azul")
        self.assertTrue(detector.classify_person(blue, proto_blue))
        self.assertFalse(detector.classify_person(black, proto_blue))

    def test_clicked_shirt_colors_override_dropdown_and_classify_correctly(self):
        yellow_rgb = detector.rgb_to_lab((235, 210, 40))
        red_rgb = detector.rgb_to_lab((200, 45, 45))
        p_y = (0.85, 0.60, *yellow_rgb)
        p_r = (0.15, 0.60, *red_rgb)
        samples = [{"t": i * 0.5, "people": [p_y] * 3 + [p_r] * 3, "cov_diff": 0.0, "end_score": 0.8}
                   for i in range(10)]
        result = detector.suggest_periods([(5.0, samples)], shirt="escura", mine_colors=[yellow_rgb])
        # Amarelo clicado está em x=0.85 (perto do gol direito end_score=0.8) -> DEFESA
        self.assertEqual(len(result[detector.DEFESA]), 1)
        self.assertEqual(result[detector.ATAQUE], [])

    def test_api_suggest_accepts_named_shirt_and_clicked_rgb_colors(self):
        client = app.app.test_client()
        fake_video = app.ROOT / "app.py"
        app.active_media["m_test"] = fake_video
        try:
            with patch("app.probe", return_value={"duration": 20.0, "width": 854, "height": 480}), \
                 patch("app.threading.Thread") as mock_thread:
                resp = client.post("/api/suggest", json={
                    "media_id": "m_test",
                    "shirt": "amarela",
                    "shirt_colors": [[235, 210, 40], [220, 195, 35]],
                    "periods": [{"start": 0, "end": 15}],
                })
                self.assertEqual(resp.status_code, 202)
                args = mock_thread.call_args.kwargs["args"]
                self.assertEqual(args[2], "amarela")
                self.assertEqual(args[4], [(235, 210, 40), (220, 195, 35)])

                bad = client.post("/api/suggest", json={
                    "media_id": "m_test",
                    "shirt": "clara",
                    "shirt_colors": [[300, 0, 0]],
                })
                self.assertEqual(bad.status_code, 400)
        finally:
            app.active_media.pop("m_test", None)


class CourtAndOutlierFilterTests(unittest.TestCase):
    def test_frame_features_keeps_top_court_player_and_rejects_bleachers_and_foreground_hands(self):
        # Quadra verde abaixo de y=0.25 (altura 200 -> y=50); arquibancada/teto escuro acima.
        frame = np.zeros((200, 320, 3), dtype=np.uint8)
        frame[:50, :] = (35, 35, 35)
        frame[50:, :] = (90, 145, 70)

        # Jogador valido no topo da quadra (y2=62 -> foot_y=0.31), camisa clara
        frame[42:62, 140:152] = (230, 230, 230)
        # Pessoa na arquibancada acima da quadra (y2=44 -> foot_y=0.22)
        frame[24:44, 70:82] = (220, 220, 220)
        # Mao na borda inferior (x1..x2 largo: w=45, h=40 -> ar=1.125, y2=196 -> foot_y=0.98)
        frame[156:196, 220:265] = (40, 40, 40)

        fake_detector = MagicMock()
        fake_detector.detect.return_value = np.array([
            [140, 42, 152, 62, 0.9],
            [70, 24, 82, 44, 0.9],
            [220, 156, 265, 196, 0.9],
        ], dtype=np.float32)

        feat = detector.frame_features(frame, fake_detector, deque(maxlen=30))
        self.assertEqual(len(feat["people"]), 1)
        self.assertAlmostEqual(feat["people"][0][0], 146 / 320, places=3)
        self.assertAlmostEqual(feat["people"][0][1], 62 / 200, places=3)

    def test_person_role_and_label_samples_discard_third_color_referee_and_goalkeeper(self):
        white = (220.0, 127.0, 129.0, 12.0)
        black = (35.0, 126.0, 130.0, 10.0)
        teal_ref = (75.0, 118.0, 121.0, 95.0)
        green_gk = (115.0, 110.0, 148.0, 110.0)

        samples = []
        for i in range(15):
            # Meu time (branco) perto do gol direito (x=0.85), adversario (preto) longe (x=0.20)
            people = (
                [(0.82, 0.60, *white), (0.85, 0.62, *white), (0.88, 0.58, *white)]
                + [(0.18, 0.60, *black), (0.21, 0.62, *black), (0.24, 0.58, *black)]
                + [(0.50, 0.55, *teal_ref), (0.10, 0.50, *green_gk)]
            )
            samples.append({"t": i * 0.5, "people": people, "cov_diff": 0.0, "end_score": 0.8})

        for kwargs in ({"shirt": "clara"}, {"mine_colors": [white[:3]]}):
            proto = detector.team_prototypes(samples, **kwargs)
            self.assertEqual(detector.person_role((0.5, 0.5, *white), proto), "meu")
            self.assertEqual(detector.person_role((0.5, 0.5, *black), proto), "adv")
            self.assertIsNone(detector.person_role((0.5, 0.5, *teal_ref), proto))
            self.assertIsNone(detector.person_role((0.5, 0.5, *green_gk), proto))
            self.assertFalse(detector.classify_person((0.5, 0.5, *teal_ref), proto))

        # Sem jogadores de linha suficientes, arbitros/goleiros sozinhos nao completam MIN_PEOPLE
        ref_heavy = [{
            "t": i * 0.5,
            "people": [(0.85, 0.60, *white)] * 2 + [(0.20, 0.60, *black)] * 2 + [(0.50, 0.55, *teal_ref)] * 4,
            "cov_diff": 0.0,
            "end_score": 0.8,
        } for i in range(10)]
        labels = detector.label_samples(ref_heavy, proto=detector.team_prototypes(samples, shirt="clara"))
        self.assertEqual(labels, [detector.INDEF] * 10)


class DiagnosticsAndBorderTests(unittest.TestCase):
    def test_low_observations_and_short_period_emit_explicit_warnings(self):
        few_samples = [
            {"t": i * 0.5, "people": [(0.85, 0.60, 220.0)] * 3 + [(0.20, 0.60, 30.0)] * 3, "cov_diff": 0.0, "end_score": 0.8}
            for i in range(6)  # 36 observacoes (< 50) e 3.0 s (< 15 s)
        ]
        diag = {}
        detector.suggest_periods([(3.0, few_samples)], shirt="clara", diagnostics_out=diag)
        self.assertTrue(diag["used_fallback"])
        self.assertEqual(diag["obs_count"], 36)
        self.assertEqual(diag["short_periods"], [3.0])
        joined = " ".join(diag["warnings"])
        self.assertIn("36 observações", joined)
        self.assertIn("curto", joined)
        self.assertIn("5 s", joined)

    def test_five_second_border_margin_preserves_full_play(self):
        # Lance real de ataque dura 4.0 s: [5.0, 9.0) em uma janela com folga [0.0, 14.0).
        atk = [(0.15, 0.60, 220.0, 128.0, 128.0, 10.0)] * 3 + [(0.85, 0.60, 30.0, 128.0, 128.0, 10.0)] * 3

        def build_window(start_t: float, end_t: float) -> list[dict]:
            items = []
            t = start_t
            while t < end_t - 1e-6:
                is_play = 5.0 <= t < 9.0
                items.append({
                    "t": round(t, 2),
                    "people": atk if is_play else [],
                    "cov_diff": 0.0,
                    "end_score": 0.8 if is_play else 0.0,
                })
                t += 0.5
            return items

        # Sem folga no inicio (corte comecando exatamente em t=5.0s, quadro inicial sem jogadores):
        tight_edge = build_window(5.0, 9.0)
        tight_edge[0]["people"] = []
        res_tight = detector.suggest_periods([(9.0, tight_edge)], shirt="clara")
        self.assertEqual(res_tight[detector.ATAQUE], [])

        # Com 5s de folga antes e depois [0.0, 14.0), o mesmo lance de 4.0s e 100% preservado:
        padded = build_window(0.0, 14.0)
        res_padded = detector.suggest_periods([(14.0, padded)], shirt="clara")
        self.assertEqual(len(res_padded[detector.ATAQUE]), 1)
        self.assertLessEqual(res_padded[detector.ATAQUE][0]["start"], 5.0)
        self.assertGreaterEqual(res_padded[detector.ATAQUE][0]["end"], 9.0)

    def test_goal_sides_auto_aligns_inverted_cov_diff_and_marks_midfield_none(self):
        # Simula quadra onde cov_diff tem sinal oposto ao end_score (ex.: rede/area cinza) + trecho neutro no meio
        samples = (
            [{"t": i * 0.5, "people": [], "cov_diff": 0.30, "end_score": -0.70} for i in range(8)]
            + [{"t": (8 + i) * 0.5, "people": [], "cov_diff": 0.01, "end_score": 0.0} for i in range(10)]
            + [{"t": (18 + i) * 0.5, "people": [], "cov_diff": -0.32, "end_score": 0.75} for i in range(8)]
        )
        sides = detector.goal_sides(samples)
        self.assertEqual(sides[2], 0.0)     # esquerda (alinhado ao end_score=-0.70, invertendo cov_diff=+0.30)
        self.assertIsNone(sides[13])        # meio de quadra neutro -> None
        self.assertEqual(sides[-2], 1.0)    # direita (alinhado ao end_score=+0.75, invertendo cov_diff=-0.32)

    def test_half_polarity_keeps_attack_intact_and_detects_halftime_flip(self):
        white = (220.0, 128.0, 128.0, 10.0)
        black = (30.0, 128.0, 128.0, 10.0)
        # 1o tempo: branco ataca na direita (end_score=+0.8); no meio do ataque pivo/pontas entram nos 6m
        atk_clear = [(0.25, 0.65, *white)] * 3 + [(0.78, 0.45, *black)] * 3
        atk_tight_6m = [(0.75, 0.50, *white)] * 3 + [(0.70, 0.55, *black)] * 3  # d_mine < d_other pontualmente
        # 2o tempo (apos intervalo): branco passa a defender na direita
        def_2nd = [(0.80, 0.45, *white)] * 3 + [(0.25, 0.65, *black)] * 3

        samples = []
        t = 0.0
        for block, es in (
            ([atk_clear] * 14, 0.8),       # 0..7s ataque claro
            ([atk_tight_6m] * 10, 0.8),    # 7..12s pivo nos 6m na mesma posse (nao deve cortar nem virar defesa)
            ([[]] * 8, 0.0),               # 12..16s intervalo
            ([def_2nd] * 24, 0.8),         # 16..28s 2o tempo: branco agora defende na direita
        ):
            for ppl in block:
                samples.append({"t": round(t, 2), "people": ppl, "cov_diff": 0.0, "end_score": es})
                t += 0.5

        res = detector.suggest_periods([(t, samples)], shirt="clara")
        self.assertEqual(len(res[detector.ATAQUE]), 1)
        self.assertGreaterEqual(res[detector.ATAQUE][0]["end"], 11.5)  # nao cortou em 7s!
        self.assertEqual(len(res[detector.DEFESA]), 1)
        self.assertGreaterEqual(res[detector.DEFESA][0]["start"], 15.5)

    def test_click_voting_ignores_accidental_background_clicks(self):
        black = (20.0, 130.0, 128.0, 5.0)
        yellow = (140.0, 126.0, 175.0, 185.0)
        blue_court = (110.0, 118.0, 95.0)  # clique acidental no piso azul (longe dos dois times)
        samples = [{"t": i * 0.5, "people": [(0.3, 0.6, *black)] * 3 + [(0.7, 0.6, *yellow)] * 3,
                    "cov_diff": 0.0, "end_score": 0.8} for i in range(12)]
        # 2 cliques certos no preto + 3 cliques acidentais no piso azul -> ainda escolhe preto mesmo com dropdown trocado!
        proto = detector.team_prototypes(
            samples,
            shirt="amarela",
            mine_colors=[black[:3], black[:3], blue_court, blue_court, blue_court],
        )
        self.assertEqual(detector.person_role((0.5, 0.5, *black), proto), "meu")
        self.assertEqual(detector.person_role((0.5, 0.5, *yellow), proto), "adv")

    def test_suggest_worker_records_warnings_in_job_and_log(self):
        job_id = app.add_job("suggest")
        few_samples = [
            {"t": i * 0.5, "people": [(0.85, 0.60, 220.0)] * 3 + [(0.20, 0.60, 30.0)] * 3, "cov_diff": 0.0, "end_score": 0.8}
            for i in range(6)
        ]
        try:
            with patch("app.probe", return_value={"duration": 3.0, "width": 854, "height": 480}), \
                 patch("detector.PersonDetector", return_value=MagicMock()), \
                 patch("detector.extract_samples", return_value=few_samples), \
                 patch("app.export_log") as mock_log:
                app.suggest_worker(job_id, app.ROOT / "app.py", "clara", [{"start": 0.0, "end": 3.0}])
            job = app.jobs[job_id]
            self.assertEqual(job["status"], "done")
            self.assertTrue(job["warnings"])
            self.assertIn("Aviso:", job["message"])
            log_texts = [call.args[1] for call in mock_log.call_args_list]
            self.assertTrue(any("aviso:" in txt for txt in log_texts))
        finally:
            app.jobs.pop(job_id, None)


if __name__ == "__main__":
    unittest.main()
