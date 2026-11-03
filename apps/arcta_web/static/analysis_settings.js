(() => {
    "use strict";
    const panel = document.getElementById("analysis-settings");
    if (!panel) return;
    const form = document.getElementById("analysis-settings-form");
    const fields = document.getElementById("analysis-settings-fields");
    const status = document.getElementById("analysis-settings-status");
    const mode = document.getElementById("analysis-settings-mode");
    const requirement = document.getElementById("analysis-settings-requirement");
    const save = document.getElementById("analysis-settings-save");
    const reset = document.getElementById("analysis-settings-reset");
    const reload = document.getElementById("analysis-settings-reload");
    const url = `/api/sessions/${encodeURIComponent(panel.dataset.sessionId)}/analysis-settings`;
    let state = null, dirty = false, busy = false;
    const inputs = new Map();

    function message(text, error = false) {
        status.textContent = text;
        status.style.color = error ? "#a12323" : "#24533e";
    }
    function lock(value) {
        busy = value;
        for (const input of inputs.values()) input.disabled = value;
        save.disabled = value || !state || !dirty;
        reset.disabled = value || !state;
        reload.disabled = value;
    }
    async function request(method, body, suffix = "") {
        const response = await fetch(url + suffix, {
            method, cache: "no-store", headers: {"Content-Type": "application/json"},
            ...(body === undefined ? {} : {body: JSON.stringify(body)})
        });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Paramètres refusés par le serveur.");
        return data;
    }
    function display(data) {
        state = data;
        if (!inputs.size) {
            for (const [key, label, unit, help] of data.fields) {
                const box = document.createElement("div");
                const title = document.createElement("label");
                const input = document.createElement("input");
                const hint = document.createElement("p");
                title.textContent = `${label} (${unit})`;
                input.id = `settings-${key}`;
                title.htmlFor = input.id;
                input.type = "number";
                input.required = key !== "subtract_selflock";
                if (key === "subtract_selflock") input.type = "checkbox";
                input.step = key === "normality_min_n" ? "1" : "any";
                input.min = key === "normality_min_n" ? "3" : "0";
                input.max = key === "normality_min_n" ? "5000" : "100";
                input.style.cssText = "width:100%;min-height:40px;font:inherit;padding:7px;border:1px solid #bfc7cf;border-radius:6px";
                if (key === "subtract_selflock") input.style.cssText = "width:24px;height:24px;display:block;margin:10px 0;accent-color:#135b88";
                hint.textContent = help;
                hint.id = input.id + "-help";
                hint.style.cssText = "font-size:.9em;color:#5b6570";
                input.setAttribute("aria-describedby", hint.id);
                box.append(title, input, hint);
                fields.append(box);
                inputs.set(key, input);
            }
        }
        for (const [key, input] of inputs) {
            if (key === "subtract_selflock") {input.checked = data.values[key]; continue;}
            input.value = key === "normality_min_n" ? data.values[key] : Number((100 * data.values[key]).toPrecision(12));
        }
        dirty = false;
        mode.textContent = data.customized ? "— personnalisés" : "— valeurs par défaut";
        requirement.textContent = `Objectif enregistré : au moins ${data.required_n} essais indépendants valides à chaque position pour la méthode non paramétrique.`;
    }
    async function perform(action, success) {
        if (busy) return;
        lock(true);
        try { display(await action()); message(success); }
        catch (error) { message(error.message, true); }
        finally { lock(false); }
    }
    form.addEventListener("input", () => {
        dirty = true;
        mode.textContent = "— modifications non enregistrées";
        requirement.textContent = "L'effectif requis sera recalculé après enregistrement.";
        message("Enregistrez vos modifications avant de poursuivre le parcours.");
        lock(false);
    });
    form.addEventListener("submit", event => {
        event.preventDefault();
        if (!state || busy || !form.reportValidity()) return;
        const values = {};
        for (const [key, input] of inputs) {
            if (key === "subtract_selflock") {values[key] = input.checked; continue;}
            const value = input.valueAsNumber;
            const count = key === "normality_min_n";
            if (!Number.isFinite(value) || (!count && (value >= 100 || (key !== "thr_ratio" && value <= 0)))) {
                message("Les pourcentages doivent être strictement compris entre 0 et 100 ; le seuil bas peut être nul.", true);
                return;
            }
            values[key] = count ? value : value / 100;
        }
        perform(() => request("PUT", {values, revision: state.revision}),
            "Paramètres enregistrés. Relancez une exécution pour produire des résultats avec ces valeurs.");
    });
    reset.addEventListener("click", () => {
        if (state) perform(() => request("POST", {revision: state.revision}, "/reset"),
            "Valeurs par défaut restaurées et enregistrées pour la prochaine exécution.");
    });
    reload.addEventListener("click", () => perform(() => request("GET"), "Paramètres enregistrés rechargés."));
    window.addEventListener("beforeunload", event => {
        if (dirty) { event.preventDefault(); event.returnValue = ""; }
    });
    // Bloque le lancement si des valeurs affichées ne sont pas enregistrées.
    document.getElementById("run-button")?.addEventListener("click", event => {
        if (dirty || busy || !state) {
            event.preventDefault(); event.stopImmediatePropagation();
            panel.open = true;
            panel.scrollIntoView({block: "center"});
            message("Enregistrez ou rechargez les paramètres avant le lancement.", true);
        }
    }, true);
    // Conserve la protection des éventuels formulaires voisins.
    document.addEventListener("submit", event => {
        if (event.target === form) return;
        if (dirty || busy || !state) {
            event.preventDefault();
            event.stopImmediatePropagation();
            panel.open = true;
            panel.scrollIntoView({block: "center"});
            message("Enregistrez les paramètres ou rechargez les valeurs enregistrées avant de lancer le calcul.", true);
        }
    }, true);
    perform(() => request("GET"), "Paramètres prêts. Les pourcentages sont affichés de 0 à 100.");
})();
