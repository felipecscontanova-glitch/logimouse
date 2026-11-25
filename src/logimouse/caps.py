"""O que cada dispositivo oferece: no proprio aparelho, feito pelo LogiMouse, ou ainda nao."""


# feature HID++ -> (nome, onde fica no painel)
FEATURE_CAPS = [
    ((0x1000, 0x1001, 0x1004, 0x1F20), "Bateria", "cartão e barra"),
    ((0x2201, 0x2202), "DPI", "Desempenho"),
    ((0x2205,), "Velocidade do ponteiro", "Desempenho"),
    ((0x8060, 0x8061), "Taxa de atualização", "Desempenho"),
    ((0x8100,), "Memória de perfis (botões e DPI no mouse)", "Botões e Perfis"),
    ((0x2110, 0x2111), "SmartShift (roda)", "Desempenho"),
    ((0x2121,), "Roda em alta resolução", "Desempenho"),
    ((0x8070, 0x8071), "Luzes", "Luzes"),
    ((0x8310,), "Equalizador gravado no fone", "Som"),
    ((0x8300,), "Retorno da voz", "Som"),
]
FEATURE_TODO = [((0x8010,), "Teclas G"), ((0x1B04,), "Botões programáveis (tipo MX)"), ((0x4521,), "Teclas Fn")]


def capabilities(d, s):
    """[(nome, "aparelho"|"LogiMouse"|"ainda não", onde)] do que o dispositivo oferece."""
    out = []
    feats = set(s.get("features") or [])
    if d.ui == "mchose":
        out.append(("Bateria", "aparelho", "cartão e barra"))
    elif d.ui == "generic":
        out.append(("Bateria", "aparelho", "cartão e barra"))
    for ids, name, where in FEATURE_CAPS:
        if feats & set(ids):
            out.append((name, "aparelho", where))
    if not feats and d.protocol and s.get("battery"):
        out.append(("Bateria", "aparelho", "cartão e barra"))
    audio = d.ui in ("mchose", "logi_headset") or getattr(d, "audio", False)
    if d.ui == "mouse":
        if s.get("onboard"):
            out += [("Macros", "LogiMouse", "Macros"), ("Perfis por programa", "LogiMouse", "Perfis")]
        out.append(("Teste de botões e rolagem", "LogiMouse", "Teste"))
    if audio:
        out += [("Redução de ruído por IA (RNNoise)", "LogiMouse", "Microfone"),
                ("Ganho e equalizador da voz", "LogiMouse", "Microfone"),
                ("Teste de microfone", "LogiMouse", "Microfone"),
                ("Surround virtual 7.1", "LogiMouse", "Som")]
        if d.ui != "logi_headset":
            out.append(("Equalizador de 10 faixas", "LogiMouse", "Som"))
    if d.ui == "mchose":
        out.append(("Correção do volume interno baixo", "LogiMouse", "Som"))
    if d.ui != "generic":
        out.append(("Aviso de bateria baixa", "LogiMouse", "Geral"))
    for ids, name in FEATURE_TODO:
        if feats & set(ids):
            out.append((name, "ainda não", ""))
    seen, uniq = set(), []
    for c in out:
        if c[0] not in seen:
            seen.add(c[0])
            uniq.append(c)
    return uniq
