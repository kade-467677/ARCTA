const arctaIsoSymbols = {"Xg": "T", "Xt": "T_th", "Xh": "T_b", "Y": "F", "A": "Θ", "A_eff": "Θ_recalé", "A0": "Θ₀", "µg": "µ_tot", "µt": "µ_th", "µh": "µ_b"};
function arctaIsoLabel(value) { return String(value).replace(/(?<![\p{L}\p{N}_])(A_eff|A0|Xg|Xt|Xh|µg|µt|µh|Y|A)(?![\p{L}\p{N}_])/gu, key => arctaIsoSymbols[key]); }
// 62F2: read-only presentation of the persisted DIAG snapshot.
window.ARCTA_DIAG_FLAG_LABELS = Object.freeze({
    OK: "RAS",
    FMAX_NO_POSITIVE_TORQUE: "Fmax : aucun couple positif avant inversion",
    FMAX_NO_ADMISSIBLE_POINT: "Fmax : aucun point dans la fenêtre de serrage",
    FMAX_PHASE_UNAVAILABLE: "Fmax : phase de serrage indéterminée",
    NO_ANGLE: "Colonne d'angle absente",
    TOO_FEW_POINTS: "Nombre de points insuffisant",
    NO_POSITIVE_TENSION: "Tension positive absente",
    A0_NOT_FOUND: "Origine élastique A0 non trouvée",
    A0_FALLBACK_WINDOW: "A0 calculée sur une fenêtre de secours",
    LOW_A0_LINEARITY: "Linéarité autour de A0 insuffisante",
    CONTACT_NOT_FOUND: "Début de mise en tension non trouvé",
    SNUG_NOT_FOUND: "Point de mise en appui non trouvé",
    TORQUE_BALANCE_WARNING: "Écart du bilan des couples à surveiller",
    TORQUE_BALANCE_INCONSISTENCY: "Incohérence du bilan des couples",
    END_UNLOADING_DETECTED: "Début de desserrage détecté",
    DIAG_EXCEPTION: "Erreur pendant le diagnostic",
    CONTACT_AFTER_SNUG: "Contact détecté après la mise en appui",
    SNUG_AFTER_A0: "Mise en appui détectée après A0",
    CONTACT_AFTER_A0: "Contact détecté après A0",
    A0_ORDER_INCOHERENT: "Ordre contact < mise en appui < A0 non vérifié",
    ISO16269_4_OUTLIER: "Valeur atypique détectée selon l'ISO 16269-4",
    SOURCE_PREPARATION_ERROR: "Impossible de préparer le fichier d'essai",
});
window.diagFlagLabel = function(code) {
    const key = String(code || "");
    return window.ARCTA_DIAG_FLAG_LABELS[key]
        || `Anomalie non référencée (${key || "code absent"})`;
};

window.renderDiagVisual = function(payload) {
    const host = document.getElementById("diag-visual");
    host.replaceChildren();
    const ns = "http://www.w3.org/2000/svg";
    if (!payload.exists) return;
    function node(tag, text, parent=host) {
        const el = document.createElement(tag);
        if (text !== undefined) el.textContent = text;
        parent.appendChild(el);
        return el;
    }
    const fmt = v => Number.isFinite(v)
        ? v.toLocaleString("fr-FR", {maximumSignificantDigits: 5}) : "—";
    const labels = {Y:"Force de serrage F (N)", Xg:"Couple de serrage T (N·m)",
        Xh:"Couple à l’appui T_b (N·m)", Xt:"Couple transmis au filetage T_th (N·m)"};
    const stored = payload.stored || {};
    const trials = stored.review?.trials || [];
    const names = new Map(trials.map(t => [t.source_id, t.source_name]));
    const curvesBlock = node("section");
    const summaryBlock = node("section");
    const boxplotsBlock = node("section");
    [summaryBlock, boxplotsBlock].forEach(block => {
        block.style.borderTop = "1px solid #dce1e6";
        block.style.marginTop = "24px";
        block.style.paddingTop = "20px";
    });
    node("h2", "Synthèse et courbes DIAG", summaryBlock);
    node("p", payload.stale ? "Résultats obsolètes : consultation uniquement."
        : "Résultats du dernier DIAG enregistré — aucun recalcul à l'affichage.", summaryBlock);
    const excluded = new Set(trials.filter(t => t.decision === "REJECTED").map(t => t.source_id));
    const rows = (stored.review_summary || []).filter(r => !excluded.has(String(r.Trial_ID)));
    node("p", "Population : essais non rejetés, acceptés ou en attente. Réévaluation automatique après rejet/réintégration. "
        + "N compte les valeurs numériques disponibles pour chaque indicateur.", summaryBlock);
    const table = node("table", undefined, summaryBlock);
    const head = node("tr", undefined, node("thead", undefined, table));
    ["Indicateur", "N", "Moyenne", "Médiane", "Min", "Max", "Écart-type (n−1)"]
        .forEach(t => node("th", t, head));
    const body = node("tbody", undefined, table);
    const metrics = {Ymax:"Force maximale au serrage (N)",
        T_at_Fmax_Nm:"Couple à Fmax au serrage (N·m)",
        Fmax_cycle_N:"Force maximale du cycle complet (N)",
        K_YA_20_50:"Raideur tension/angle, 20–50 % (N/°)",
        Xgmax:"Couple maximal (N·m)",
        Autofrein_Xg_preA0_med:"Couple global médian avant A0 (N·m)",
        DeadTravel_DeltaA_deg:"Course morte après inversion (°)",
        Residual_Thread_Torque_Median_Nm:"Couple filet résiduel Xt (N·m)",
        Residual_Torsional_Stress_Nominal_MPa:"Contrainte nominale de torsion résiduelle (MPa)",
        Reverse_Pickup_Aeff_deg:"Angle de reprise inverse Xg (° recalé)",

        Score_Comportement_Global:"Score comportement global",
        Score_Comparatif_Population:"Score comparatif population"};
    for (const [key, label] of Object.entries(metrics)) {
        const values = rows.map(r => r[key]).filter(v => typeof v === "number"
            && Number.isFinite(v)).sort((a,b) => a-b);
        const n = values.length;
        const mean = n ? values.reduce((a,b) => a+b, 0)/n : NaN;
        const median = n ? (values[Math.floor((n-1)/2)] + values[Math.floor(n/2)])/2 : NaN;
        const sd = n > 1 ? Math.sqrt(values.reduce((a,b) => a+(b-mean)**2,0)/(n-1)) : NaN;
        const row = node("tr", undefined, body);
        [arctaIsoLabel(label), String(n), fmt(mean), fmt(median), fmt(values[0]),
            fmt(values[n-1]), fmt(sd)].forEach(t => node("td",t,row));
    }
    node("h2", "Boîtes à moustaches DIAG — ISO 16269-4", boxplotsBlock);
    const hiddenDecisionVariables = new Set([
        "A0_elastic_Y", "A0_snug_from_Xg_threshold_eff", "K_XgA_20_50", "R2_XgA_20_50", "Effective_Loosening_Aeff_deg", "N_A0_fit", "Aeff_max",
        "R2_A0_fit",
        "A_elastic_start_eff",
        "A_elastic_end_eff",
        "Unwind_Plateau_Y_delta_rel",
        "Unwind_Plateau_DeltaA_deg",
        "Unwind_Plateau_Xt_mean_Nm",
        "Unwind_Plateau_Xt_median_Nm",
        "Intercept_YA_20_50",
        "Autofrein_Xg_minus_Xt_preA0_med",
        "Autofrein_Xg_over_Xt_preA0_med",
    ]);
    const rawBoxRows = (stored.diag_boxplots || []).filter(r => !excluded.has(String(r.Trial_ID)));
    const boxRows = rawBoxRows.filter(row =>
        String(row.Source_Sheet || "") !== "DIAG_BALANCE"
        && !hiddenDecisionVariables.has(String(row.Variable || ""))
    );
    if (!boxRows.length) {
        node("p", "Boîtes DIAG non disponibles pour cette revue. Une relance explicite du DIAG est nécessaire après installation de 62G1A.", boxplotsBlock);
    } else {
        const visibleVariableCount = new Set(
            boxRows.map(row => String(row.Variable || "")).filter(Boolean)
        ).size;
        node("p", `${visibleVariableCount} indicateurs décisionnels affichés. `
            + "Les indicateurs techniques masqués restent calculés et archivés dans l'export Excel.",
            boxplotsBlock);
        const boxControls = node("div", undefined, boxplotsBlock);
        boxControls.style.display = "flex";
        boxControls.style.flexWrap = "wrap";
        boxControls.style.gap = "10px";
        boxControls.style.alignItems = "center";
        const scopeLabel = node("label", "Périmètre : ", boxControls);
        const scopeSelect = node("select", undefined, scopeLabel);
        [["FULL", "Tous les indicateurs décisionnels"], ["SHORT", "Synthèse courte"]]
            .forEach(([value, text]) => {
                const option = node("option", text, scopeSelect);
                option.value = value;
            });
        const previous = node("button", "Page précédente", boxControls);
        previous.type = "button";
        const next = node("button", "Page suivante", boxControls);
        next.type = "button";
        const pageLabel = node("span", "", boxControls);
        const boxLegend = node("div", undefined, boxplotsBlock);
        boxLegend.style.display = "flex";
        boxLegend.style.flexWrap = "wrap";
        boxLegend.style.gap = "8px 18px";
        boxLegend.style.margin = "10px 0 4px";
        boxLegend.style.fontSize = "0.9rem";
        [
            ["● RAS", "#4f6f52"],
            ["● À surveiller", "#d97706"],
            ["● Écart majeur", "#b42318"],
            ["┆ Seuil d'alerte", "#d97706"],
            ["┆ Seuil critique", "#b42318"],
        ].forEach(([text, color]) => {
            const item = node("span", text, boxLegend);
            item.style.color = color;
            item.style.fontWeight = "600";
        });
        const boxHost = node("div", undefined, boxplotsBlock);
        boxHost.style.display = "grid";
        boxHost.style.gridTemplateColumns = "repeat(auto-fit, minmax(520px, 1fr))";
        boxHost.style.gap = "14px";
        boxHost.style.marginTop = "12px";
        let boxPage = 0;

        function finiteField(row, ...keys) {
            for (const key of keys) {
                if (row?.[key] == null) continue;
                const value = Number(row[key]);
                if (Number.isFinite(value)) return value;
            }
            return NaN;
        }
        function renderBoxplots() {
            boxHost.replaceChildren();
            const short = scopeSelect.value === "SHORT";
            const scoped = short ? boxRows.filter(row => row.Short_Selected === true) : boxRows;
            const variables = [...new Set(scoped.map(row => String(row.Variable || "")))]
                .filter(Boolean);
            const pageCount = Math.max(1, Math.ceil(variables.length / 4));
            boxPage = Math.max(0, Math.min(boxPage, pageCount - 1));
            const pageVariables = variables.slice(boxPage * 4, boxPage * 4 + 4);
            pageLabel.textContent = `Page ${boxPage + 1}/${pageCount}`;
            previous.disabled = boxPage === 0;
            next.disabled = boxPage >= pageCount - 1;
            if (!pageVariables.length) {
                node("p", "Aucun indicateur disponible pour ce périmètre.", boxHost);
                return;
            }
            pageVariables.forEach(variable => {
                const subset = scoped.filter(row => String(row.Variable) === variable
                    && Number.isFinite(Number(row.Value)));
                if (!subset.length) return;
                const first = subset[0];
                if (first.Method_Status === "TOO_FEW_VALUES") {
                    const card = node("div", undefined, boxHost);
                    node("h4", arctaIsoLabel(first.Description_FR || variable), card);
                    node("p", `Population insuffisante : ${first.N} valeurs, au moins 5 nécessaires.`, card);
                    return;
                }
                const values = subset.map(row => Number(row.Value));
                const q1 = finiteField(first, "Q1");
                const q3 = finiteField(first, "Q3");
                const median = finiteField(first, "Median");
                const warnLow = finiteField(first, "Lower_Fence_Warn", "IQR_Low_Warn");
                const warnHigh = finiteField(first, "Upper_Fence_Warn", "IQR_High_Warn");
                const failLow = finiteField(first, "Lower_Fence_Fail", "IQR_Low_Fail");
                const failHigh = finiteField(first, "Upper_Fence_Fail", "IQR_High_Fail");
                const extent = values.concat([q1, q3, median, warnLow, warnHigh, failLow, failHigh])
                    .filter(Number.isFinite);
                let xmin = Math.min(...extent), xmax = Math.max(...extent);
                if (!(xmax > xmin)) { xmin -= 0.5; xmax += 0.5; }
                const margin = (xmax - xmin) * 0.06;
                xmin -= margin; xmax += margin;
                const scale = value => 70 + 690 * (value - xmin) / (xmax - xmin);
                const card = node("div", undefined, boxHost);
                card.style.border = "1px solid #d8dee5";
                card.style.borderRadius = "8px";
                card.style.padding = "10px";
                node("h4", arctaIsoLabel(first.Description_FR || variable), card);
                node("p", `${variable} — unité : ${first.Unit || "–"} — N=${values.length}`, card);
                const svg = svgNode("svg", {viewBox:"0 0 820 230", role:"img",
                    "aria-label":`Boîte à moustaches ${first.Description_FR || variable}`}, card);
                svg.style.width = "100%";
                svg.style.minHeight = "180px";
                svgNode("line", {x1:70,x2:760,y1:170,y2:170,stroke:"#64748b","stroke-width":2}, svg);
                for (let i=0;i<=4;i++) {
                    const value=xmin+(xmax-xmin)*i/4;
                    const x=scale(value);
                    svgNode("line",{x1:x,x2:x,y1:165,y2:178,stroke:"#64748b","stroke-width":2},svg);
                    svgNode("text",{x,y:202,"text-anchor":"middle","font-size":15,fill:"#334155"},svg,fmt(value));
                }
                [[failLow,"#b42318","3 3"],[failHigh,"#b42318","3 3"],
                    [warnLow,"#d97706","6 4"],[warnHigh,"#d97706","6 4"]]
                    .forEach(([value,color,dash]) => {
                        if (Number.isFinite(value)) svgNode("line",{x1:scale(value),x2:scale(value),y1:25,y2:158,
                            stroke:color,"stroke-width":2,"stroke-dasharray":dash},svg);
                    });
                const vmin=Math.min(...values), vmax=Math.max(...values);
                svgNode("line",{x1:scale(vmin),x2:scale(vmax),y1:96,y2:96,stroke:"#315f8c","stroke-width":3},svg);
                svgNode("line",{x1:scale(vmin),x2:scale(vmin),y1:78,y2:114,stroke:"#315f8c","stroke-width":3},svg);
                svgNode("line",{x1:scale(vmax),x2:scale(vmax),y1:78,y2:114,stroke:"#315f8c","stroke-width":3},svg);
                if (Number.isFinite(q1) && Number.isFinite(q3))
                    svgNode("rect",{x:scale(q1),y:64,width:Math.max(1,scale(q3)-scale(q1)),height:64,
                        fill:"#dceeff",stroke:"#315f8c","stroke-width":2},svg);
                if (Number.isFinite(median))
                    svgNode("line",{x1:scale(median),x2:scale(median),y1:56,y2:136,stroke:"#172554","stroke-width":4},svg);
                subset.forEach((row,index) => {
                    const level=String(row.Outlier_Level || "OK").toUpperCase();
                    const color={OK:"#4f6f52",WARNING:"#d97706",FAIL:"#b42318"}[level] || "#5b6570";
                    const point=svgNode("circle",{cx:scale(Number(row.Value)),cy:76+(index%5)*10,r:6,
                        fill:color,stroke:"#ffffff","stroke-width":1.5},svg);
                    svgNode("title",{},point,`${names.get(String(row.Trial_ID)) || row.Trial_ID} : ${fmt(Number(row.Value))} (${level})`);
                });
                svgNode("text",{x:415,y:224,"text-anchor":"middle","font-size":15,fill:"#334155"},svg,
                    `Unité : ${first.Unit || "–"}`);
                const fiveNumbers = node("p",
                    `Min ${fmt(vmin)}  •  Q1 ${fmt(q1)}  •  Médiane ${fmt(median)}  •  Q3 ${fmt(q3)}  •  Max ${fmt(vmax)}`,
                    card);
                fiveNumbers.style.margin = "4px 0 2px";
                fiveNumbers.style.fontWeight = "600";
                fiveNumbers.style.color = "#334155";
            });
        }
        previous.addEventListener("click", () => { boxPage -= 1; renderBoxplots(); });
        next.addEventListener("click", () => { boxPage += 1; renderBoxplots(); });
        scopeSelect.addEventListener("change", () => { boxPage = 0; renderBoxplots(); });
        renderBoxplots();
    }
    node("h2", "Courbes des essais", curvesBlock);
    node("p", "Données de la fenêtre nettoyée DIAG ; angle recentré sur l'origine élastique. "
        + "Valeurs dans les unités attendues par le moteur : N, N·m et degrés. "
        + "Aucune conversion d'unité supplémentaire n'est effectuée ici.", curvesBlock);
    const curves = stored.visual_curves || [];
    if (!curves.length) {
        node("p", "Courbes non disponibles pour cette revue (ancienne version ou DIAG sans courbe exploitable). "
            + "Une relance explicite du DIAG est nécessaire ; elle remplace la revue et ses décisions.", curvesBlock);
        return;
    }
    const controls = node("div", undefined, curvesBlock);
    controls.style.display = "flex";
    controls.style.flexWrap = "wrap";
    controls.style.gap = "12px";
    controls.style.alignItems = "center";
    const trialLabel = node("label", "Essai de référence : ", controls);
    const select = node("select", undefined, trialLabel);
    const channelLabel = node("label", "Grandeur : ", controls);
    const channel = node("select", undefined, channelLabel);
    const overlayLabel = node("label", undefined, controls);
    const overlay = node("input", undefined, overlayLabel);
    overlay.type = "checkbox";
    overlay.id = "diag-overlay-all";
    overlay.checked = true;
    overlayLabel.append(" Superposer tous les essais");
    const detail = node("div", undefined, curvesBlock);
    const graph = node("div", undefined, curvesBlock);
    const palette = ["#12689b", "#c2410c", "#15803d", "#7e22ce", "#be123c",
        "#0f766e", "#a16207", "#4338ca", "#4b5563", "#0891b2"];
    const markerDefs = {
        fmax: ["Fmax au serrage", "#be123c"],
        contact: ["Contact", "#9a3412"],
        snug: ["Mise en appui", "#7e22ce"],
        elastic_start: ["Début fenêtre élastique", "#15803d"],
        a0: ["A0", "#111827"],
        elastic_end: ["Fin fenêtre élastique", "#15803d"],
    };
    function svgNode(tag, attrs, parent, text) {
        const el = document.createElementNS(ns, tag);
        for (const [key,value] of Object.entries(attrs)) el.setAttribute(key, value);
        if (text !== undefined) el.textContent = text;
        parent.appendChild(el);
        return el;
    }
    curves.forEach((c,i) => {
        const o=node("option", names.get(c.source_id) || c.source_id, select);
        o.value=i;
    });
    const allChannels = [...new Set(curves.flatMap(c => Object.keys(c.series || {})))];
    allChannels.forEach(key => {
        const o=node("option",labels[key] || key,channel);
        o.value=key;
    });
    function points(curve, key) {
        const y = curve.series?.[key] || [];
        return (curve.x || []).map((x,i) => [x,y[i]]).filter(
            p => p.every(v => typeof v === "number" && Number.isFinite(v))
        );
    }
    function pathData(curve, key, sx, sy) {
        const y = curve.series?.[key] || [];
        let d="", pen=false;
        (curve.x || []).forEach((x,i) => {
            if (![x,y[i]].every(v => typeof v === "number" && Number.isFinite(v))) {
                pen=false; return;
            }
            d += `${pen ? "L" : "M"}${sx(x)} ${sy(y[i])} `; pen=true;
        });
        return d;
    }
    function draw() {
        graph.replaceChildren(); detail.replaceChildren();
        const reference = curves[Number(select.value)];
        const key=channel.value;
        const scalar = rows.find(r => String(r.Trial_ID) === reference.source_id) || {};
        node("h4", `Détail — ${names.get(reference.source_id) || reference.source_id}`, detail);
        for (const [k,label] of Object.entries(metrics))
            node("div", `${arctaIsoLabel(label)} : ${fmt(scalar[k])}`,detail);
        const afStatus = {
            VALID:"valide pour correction", INSUFFICIENT_DATA:"points insuffisants",
            INCOMPLETE_WINDOW:"fenêtre incomplète", ROTATION_NOT_CONTINUOUS:"rotation non continue",
            NON_FINITE_MEASUREMENTS:"mesures manquantes", FORCE_ZERO_NOT_CHECKABLE:"zéro force non vérifiable",
            FORCE_NOT_ZERO:"force non nulle", CONTACT_IN_OR_BEFORE_WINDOW:"contact dans/avant la fenêtre",
            NEGATIVE_TORQUE:"couple négatif"
        };
        if (scalar.Autofrein_Window_Mode === "A0_MINUS_3_TO_MINUS_1_TURNS_V1") {
            node("p", `Autofrein [−1080° ; −360°] : ${afStatus[scalar.Autofrein_Status] || scalar.Autofrein_Status}. `+
                `n=${scalar.N_points_autofrein_preA0} ; médiane=${fmt(scalar.Autofrein_Xg_preA0_med)} N·m ; `+
                `écart-type=${fmt(scalar.Autofrein_Xg_preA0_std)} N·m ; seuil zéro force=${fmt(scalar.Autofrein_Force_Limit_N)} N.`,detail);
            if (scalar.Autofrein_Rotation_Message) {
                node("p", `Contrôle de rotation : ${scalar.Autofrein_Rotation_Message}`, detail);
            }
        } else node("p", "Autofrein : ancienne méthode ou indisponible. Relancer le DIAG avant correction du couple.",detail);
        const displayed = (overlay.checked ? curves : [reference])
            .filter(c => points(c,key).length);
        const valid = displayed.flatMap(c => points(c,key));
        if (!valid.length) {node("p","Aucun point exploitable pour cette grandeur.",graph); return;}
        let xmin=Infinity,xmax=-Infinity,ymin=Infinity,ymax=-Infinity;
        valid.forEach(([x,y]) => {xmin=Math.min(xmin,x); xmax=Math.max(xmax,x);
            ymin=Math.min(ymin,y); ymax=Math.max(ymax,y);});
        const dx=xmax-xmin || 1, dy=ymax-ymin || 1;
        const sx=x=>80+680*(x-xmin)/dx, sy=y=>310-270*(y-ymin)/dy;
        const svg=svgNode("svg",{viewBox:"0 0 800 370",role:"img",
            "aria-label":`${overlay.checked ? "Superposition" : names.get(reference.source_id) || reference.source_id} — ${labels[key]}`},graph);
        svg.style.width="100%"; svg.style.maxWidth="1000px";
        svgNode("title",{},svg,`${overlay.checked ? "Superposition des essais" : names.get(reference.source_id) || reference.source_id} — ${labels[key]}`);
        if (scalar.Autofrein_Window_Mode === "A0_MINUS_3_TO_MINUS_1_TURNS_V1") {
            const a=Math.max(xmin,-1080), b=Math.min(xmax,-360);
            if(b>a) svgNode("rect",{x:sx(a),y:40,width:sx(b)-sx(a),height:270,
                fill:scalar.Autofrein_Status==="VALID"?"#0d9488":"#d97706",opacity:.12},svg);
        }
        svgNode("path",{d:"M80 40V310H760",fill:"none",stroke:"#475569"},svg);
        for(let i=0;i<=4;i++) {
            const x=xmin+dx*i/4, y=ymin+dy*i/4;
            svgNode("text",{x:sx(x),y:332,"text-anchor":"middle","font-size":12},svg,fmt(x));
            svgNode("text",{x:73,y:sy(y)+4,"text-anchor":"end","font-size":12},svg,fmt(y));
        }
        svgNode("text",{x:420,y:360,"text-anchor":"middle"},svg,"Angle recalé Θ (°)");
        svgNode("text",{x:80,y:22},svg,labels[key] || key);
        displayed.forEach((curve,index) => {
            const color=palette[index % palette.length];
            const d=pathData(curve,key,sx,sy);
            svgNode("path",{d,fill:"none",stroke:color,"stroke-width":2,
                opacity:overlay.checked ? 0.78 : 1},svg);
            const p=points(curve,key);
            if(p.length===1) svgNode("circle",{cx:sx(p[0][0]),cy:sy(p[0][1]),r:4,fill:color},svg);
        });
        const markers = reference.markers || {};
        Object.entries(markerDefs).forEach(([marker,[label,color]],i) => {
            const value=markers[marker];
            if (!Number.isFinite(value) || value < xmin || value > xmax) return;
            const x=sx(value);
            svgNode("line",{x1:x,x2:x,y1:40,y2:310,stroke:color,
                "stroke-width":1.4,"stroke-dasharray":marker.includes("elastic") ? "3 3" : "6 4"},svg);
            svgNode("text",{x:x+3,y:52+i*14,"font-size":11,fill:color},svg,`${label} (${fmt(value)}°)`);
        });
        if (overlay.checked) {
            const legend=node("div", undefined, graph);
            legend.style.display="flex"; legend.style.flexWrap="wrap"; legend.style.gap="10px";
            displayed.forEach((curve,index) => {
                const item=node("span", `■ ${names.get(curve.source_id) || curve.source_id}`,legend);
                item.style.color=palette[index % palette.length];
            });
            node("p", "Les repères verticaux et les scalaires correspondent à l'essai de référence sélectionné.", graph);
        }
        node("p",`${valid.length} points affichés — aucun sous-échantillonnage.`,graph);
    }
    select.addEventListener("change",draw);
    channel.addEventListener("change",draw);
    overlay.addEventListener("change",draw);
    draw();
};
