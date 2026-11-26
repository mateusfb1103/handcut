import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import metricas  # noqa: E402
import micro_gabarito  # noqa: E402


class ParseGabaritoTests(unittest.TestCase):
    def test_parses_all_directives_and_comments(self):
        text = """
        # comentário inicial
        emenda 1:22.5
        ignorar 2:46 2:50
        ataque 0:20 0:44
        defesa 0:45 0:52 opcional # lance ambíguo
        """
        g = metricas.parse_gabarito(text)
        self.assertEqual(g.emendas, [82.5])
        self.assertEqual(g.ignorar, [(166.0, 170.0)])
        self.assertEqual(len(g.lances), 2)
        self.assertFalse(g.lances[0].optional)
        self.assertTrue(g.lances[1].optional)

    def test_invalid_line_raises_value_error(self):
        with self.assertRaises(ValueError):
            metricas.parse_gabarito("ataque 1:00 0:30")


class MetricasAvaliacaoTests(unittest.TestCase):
    def test_recall_sums_split_pieces_and_marks_partido(self):
        # Lance 1 (10s): dois pedaços de 4s cada -> soma 80% >= 50% (encontrado e partido)
        # Lance 2 (10s): um pedaço de 4s -> 40% < 50% (perdido)
        g = metricas.parse_gabarito("ataque 10 20\nataque 30 40")
        sugestoes = [{"start": 10, "end": 14}, {"start": 15, "end": 19}, {"start": 30, "end": 34}]
        res = metricas.avaliar(g, sugestoes, metricas.ATAQUE)
        self.assertEqual(res["lances"], 2)
        self.assertEqual(res["encontrados"], 1)
        self.assertEqual(res["partidos"], 1)
        self.assertAlmostEqual(res["recall"], 0.5)
        self.assertEqual(res["corretas"], 3)  # parciais contam como corretas
        self.assertEqual(res["erradas"], 0)

    def test_wrong_suggestions_type_trocado_and_fora(self):
        g = metricas.parse_gabarito("ataque 10 20\ndefesa 30 40")
        sugestoes = [
            {"start": 12, "end": 16},   # correta (parcial dentro do ataque)
            {"start": 31, "end": 37},   # errada: tipo trocado (cai na defesa)
            {"start": 50, "end": 58},   # errada: fora de qualquer lance
        ]
        res = metricas.avaliar(g, sugestoes, metricas.ATAQUE)
        self.assertEqual(res["corretas"], 1)
        self.assertEqual(res["erradas"], 2)
        self.assertEqual(res["erradas_tipo_trocado"], 1)
        self.assertEqual(res["erradas_fora_de_lance"], 1)
        self.assertAlmostEqual(res["erradas_por_correta"], 2.0)

    def test_piso_sobreposicao_filters_tiny_touches(self):
        g = metricas.parse_gabarito("ataque 10 20")
        sugestoes = [{"start": 19.5, "end": 28.0}]  # só 0.5 s de toque
        sem_piso = metricas.avaliar(g, sugestoes, metricas.ATAQUE)
        self.assertEqual(sem_piso["corretas"], 1)
        self.assertEqual(sem_piso["corretas_com_menos_de_2s"], 1)

        com_piso = metricas.avaliar(g, sugestoes, metricas.ATAQUE, piso_segundos=2.0, piso_fracao=0.25)
        self.assertEqual(com_piso["corretas"], 0)
        self.assertEqual(com_piso["erradas_fora_de_lance"], 1)

    def test_optional_and_emenda_and_ignorar(self):
        g = metricas.parse_gabarito("""
            emenda 60
            ignorar 100 110
            ataque 10 20
            defesa 30 38 opcional
        """)
        sugestoes = [
            {"start": 10, "end": 20},   # correta
            {"start": 30, "end": 38},   # cai em lance opcional -> neutra
            {"start": 56, "end": 64},   # inteiramente dentro de emenda 60 ±5s -> ignorada
            {"start": 101, "end": 109}, # inteiramente dentro de ignorar -> ignorada
        ]
        res = metricas.avaliar(g, sugestoes, metricas.ATAQUE)
        self.assertEqual(res["sugestoes"], 2)
        self.assertEqual(res["corretas"], 1)
        self.assertEqual(res["neutras"], 1)
        self.assertEqual(res["erradas"], 0)

    def test_invertido_somar_and_veredito(self):
        g = metricas.parse_gabarito("ataque 10 20\ndefesa 30 40").invertido()
        self.assertEqual([(l.kind, l.start, l.end) for l in g.lances], [("defesa", 10.0, 20.0), ("ataque", 30.0, 40.0)])
        res1 = metricas.avaliar(g, [{"start": 30, "end": 40}], metricas.ATAQUE)
        res2 = metricas.avaliar(g, [{"start": 10, "end": 20}], metricas.DEFESA)
        total = metricas.somar([res1, res2])
        self.assertAlmostEqual(total["recall"], 1.0)
        self.assertAlmostEqual(total["erradas_por_correta"], 0.0)
        est = metricas.estimativa_revisao(total["sugestoes"], total["partidos"], 120.0)
        v = metricas.veredito(total, tempo_relativo=0.25, revisao_por_jogo=est["segundos_por_jogo"])
        self.assertEqual(v, {"recall": True, "erradas_por_correta": True, "revisao_estimada": True, "tempo_analise": True})


class MicroGabaritoTests(unittest.TestCase):
    def test_evaluate_signals_scores_goal_team_and_outside_discard(self):
        truth = {
            "frames": [
                {
                    "t": 0.0,
                    "lado_gol": "D",
                    "pessoas": [
                        {"cx": 0.2, "foot_y": 0.6, "classe": "meu"},
                        {"cx": 0.4, "foot_y": 0.6, "classe": "adv"},
                        {"cx": 0.8, "foot_y": 0.5, "classe": "fora"},
                    ],
                },
                {
                    "t": 6.0,
                    "lado_gol": "E",
                    "pessoas": [
                        {"cx": 0.3, "foot_y": 0.7, "classe": "meu"},
                        {"cx": 0.6, "foot_y": 0.7, "classe": "fora"},
                    ],
                },
            ]
        }
        pred = {
            "frames": [
                {
                    "t": 0.0,
                    "lado_gol": "D",
                    "pessoas": [
                        {"cx": 0.205, "foot_y": 0.605, "classe": "meu"},
                        {"cx": 0.405, "foot_y": 0.605, "classe": "meu"},   # erro de time
                        {"cx": 0.805, "foot_y": 0.505, "classe": "fora"},  # descartado como fora
                    ],
                },
                {
                    "t": 6.0,
                    "lado_gol": "D",  # erro de lado do gol
                    "pessoas": [
                        {"cx": 0.305, "foot_y": 0.705, "classe": "meu"},
                        # pessoa 'fora' em 0.6 não detectada / filtrada antes -> também conta como descartada!
                    ],
                },
            ]
        }
        res = micro_gabarito.evaluate_signals(truth, pred)
        self.assertEqual((res["lado_gol_ok"], res["lado_gol_total"]), (1, 2))
        self.assertEqual((res["time_ok"], res["time_total"]), (2, 3))
        self.assertEqual((res["fora_descartados"], res["fora_total"]), (2, 2))
        self.assertEqual((res["jogadores_mantidos"], res["jogadores_total"]), (3, 3))


if __name__ == "__main__":
    unittest.main()
