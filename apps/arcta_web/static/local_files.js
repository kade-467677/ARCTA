(() => {
    let busy = false;
    const byId = id => document.getElementById(id);
    const sessionId = () => typeof currentSession !== "undefined" ? currentSession?.session_id :
        (typeof SESSION_ID !== "undefined" ? SESSION_ID : null);
    const message = text => {
        const target = byId("upload-status") || byId("source-origin");
        if (target) target.textContent = text;
    };
    async function json(response) {
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
        return data;
    }
    async function refresh() {
        const id = sessionId();
        if (!id) return;
        try {
            const data = await json(await fetch(`/api/sessions/${encodeURIComponent(id)}/local-files`));
            if (id !== sessionId()) return;
            for (const [button, input] of [["local-trials", "trial-files"], ["local-config", "config-file"]]) {
                if (byId(button)) { byId(button).hidden = !data.native_available; byId(button).disabled = busy; }
                if (byId(input)) byId(input).hidden = data.native_available;
            }
            if (byId("choose-output-directory")) byId("choose-output-directory").hidden = !data.native_available;
            if (byId("output-source-directory") && !byId("output-source-directory").dataset.edited)
                byId("output-source-directory").value = data.destination_directory;
            if (byId("output-central-root")) byId("output-central-root").textContent = (byId("output-central-root").dataset.pathOnly ? "" : "Résultats centralisés : ") + data.central_root;
            if (byId("source-origin")) byId("source-origin").textContent = data.origin_directory ?
                (byId("source-origin").dataset.pathOnly ? "" : "Origine des essais : ") + data.origin_directory :
                "Origine non enregistrée pour ces anciens imports. La sélection locale des essais la mémorise automatiquement.";
            document.querySelectorAll("[data-origin-id]").forEach(element => {
                element.textContent = "Fichier d’origine : " + (data.source_paths[element.dataset.originId] || "non renseigné");
            });
        } catch (error) { message(error.message); }
    }
    async function select(mode) {
        const id = sessionId();
        if (!id || busy) return;
        busy = true;
        if (byId("confirm-sources")) byId("confirm-sources").disabled = true;
        const controls = ["local-trials", "local-config", "choose-output-directory", "new-session-button", "run-button"]
            .map(byId).filter(Boolean);
        const previous = controls.map(control => control.disabled);
        controls.forEach(control => { control.disabled = true; });
        message("Sélection Windows ouverte…");
        try {
            const result = await json(await fetch(`/api/sessions/${encodeURIComponent(id)}/local-files/${mode}`, {
                method: "POST", headers: {"X-ARCTA-Local": "1"}
            }));
            if (id !== sessionId()) return;
            if (mode === "directory" && !result.cancelled) {
                const field = byId("output-source-directory");
                field.value = result.destination_directory;
                delete field.dataset.edited;
            }
            if (typeof refreshSession === "function") await refreshSession();
            await refresh();
            if (result.cancelled) message("Sélection annulée ; aucun changement.");
            else if (mode !== "directory") message(`${result.imported} fichier(s) importé(s). ${(result.errors || []).join(" | ")}`);
        } catch (error) { message(error.message); }
        finally {
            busy = false;
            if (typeof updateWorkflow === "function") updateWorkflow(currentSession);
            controls.forEach((control, index) => { control.disabled = previous[index]; });
        }
    }
    byId("local-trials")?.addEventListener("click", () => select("TRIAL"));
    byId("local-config")?.addEventListener("click", () => select("CONFIG"));
    byId("choose-output-directory")?.addEventListener("click", () => select("directory"));
    byId("output-source-directory")?.addEventListener("input", event => { event.target.dataset.edited = "1"; });
    window.arctaLocalRefresh = refresh;
    refresh();
})();
