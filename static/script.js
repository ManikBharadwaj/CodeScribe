document.addEventListener("DOMContentLoaded", () => {
    const appContainer = document.getElementById("appContainer");
    const loginCard = document.getElementById("loginCard");
    const registerCard = document.getElementById("registerCard");
    const workbenchCard = document.getElementById("workbenchCard");
    const loginForm = document.getElementById("loginForm");
    const registerForm = document.getElementById("registerForm");
    const loginMessage = document.getElementById("loginMessage");
    const registerMessage = document.getElementById("registerMessage");
    const workbenchMessage = document.getElementById("workbenchMessage");
    const workspaceSelect = document.getElementById("workspaceSelect");
    const vaultWorkspaceName = document.getElementById("vaultWorkspaceName");
    const fileList = document.getElementById("fileList");
    const fileNameInput = document.getElementById("fileNameInput");
    const languageSelect = document.getElementById("languageSelect");
    const fileUploadInput = document.getElementById("fileUploadInput");
    const codeEditor = document.getElementById("codeEditor");
    const editorGutter = document.getElementById("editorGutter");
    const editorStatusLanguage = document.getElementById("editorStatusLanguage");
    const editorStatusLines = document.getElementById("editorStatusLines");
    const editorDirty = document.getElementById("editorDirty");
    const saveState = document.getElementById("saveState");
    const fileTabName = document.getElementById("fileTabName");
    const fileExtension = document.getElementById("fileExtension");
    const analysisResults = document.getElementById("analysisResults");
    const analysisEmptyState = document.getElementById("analysisEmptyState");
    const syntaxBanner = document.getElementById("syntaxBanner");
    const analysisSummary = document.getElementById("analysisSummary");
    const conceptList = document.getElementById("conceptList");
    const complexityTime = document.getElementById("complexityTime");
    const complexitySpace = document.getElementById("complexitySpace");
    const complexitySpikes = document.getElementById("complexitySpikes");
    const suggestionList = document.getElementById("suggestionList");
    const hintList = document.getElementById("hintList");
    const btnAnalyzeRaw = document.getElementById("btnAnalyzeRaw");
    const btnSaveFile = document.getElementById("btnSaveFile");

    let activeWorkspaceId = null;
    let activeFileId = null;
    let analysisTimer = null;
    let analysisRequestId = 0;

    const metrics = {
        lines: document.getElementById("metricSLOC"),
        functions: document.getElementById("metricFunctions"),
        loops: document.getElementById("metricLoops"),
        conditionals: document.getElementById("metricConditionals"),
        classes: document.getElementById("metricClasses"),
        complexity: document.getElementById("metricComplexity"),
        recursions: document.getElementById("metricRecursions")
    };

    function showCard(card) {
        [loginCard, registerCard, workbenchCard].forEach(item => item.classList.add("hidden"));
        card.classList.remove("hidden");
        appContainer.classList.toggle("workbench-active", card === workbenchCard);
    }

    function buddyError(message) {
        const known = {
            "Invalid email or password.": "Email ya password match nahi hua. Dobara check karke try karein.",
            "Authentication required.": "Session expire ho gaya. Login karke continue karein.",
            "Code content is empty.": "Editor mein code nahi hai. Code paste karke scan karein.",
            "Request body must be a JSON object.": "Request format match nahi hua. Refresh karke dobara try karein."
        };
        if (known[message]) return known[message];
        return `Kuch gadbad hui: ${message || "Request complete nahi hui."} Thodi der baad dobara try karein.`;
    }

    function setMessage(element, text, isError) {
        if (!element) return;
        element.textContent = text;
        element.className = `message ${isError ? "error" : "success"}`;
    }

    function clearMessage(element) {
        if (!element) return;
        element.textContent = "";
        element.className = "message";
    }

    async function requestJson(url, options) {
        let response;
        const controller = new AbortController();
        const timeout = window.setTimeout(() => controller.abort(), 15000);
        try {
            response = await fetch(url, { ...options, signal: controller.signal });
        } catch (error) {
            if (error.name === "AbortError") {
                throw new Error("Request timeout ho gaya. Network check karke dobara try karein.");
            }
            throw new Error("Server se connection nahi hua. Network check karke dobara try karein.");
        } finally {
            window.clearTimeout(timeout);
        }
        let data;
        try {
            data = await response.json();
        } catch (error) {
            throw new Error("Server response samajh nahi aaya. Refresh karke dobara try karein.");
        }
        if (!response.ok) {
            throw new Error(buddyError(data.error || `Request failed (${response.status}).`));
        }
        return data;
    }

    function updateGutter() {
        const count = Math.max(1, codeEditor.value.split("\n").length);
        editorGutter.textContent = Array.from({ length: count }, (_, index) => index + 1).join("\n");
        editorStatusLines.textContent = `${count} ${count === 1 ? "line" : "lines"}`;
        editorGutter.scrollTop = codeEditor.scrollTop;
    }

    function updateFileMeta() {
        const filename = fileNameInput.value.trim() || "untitled";
        const extension = filename.includes(".") ? `.${filename.split(".").pop().toLowerCase()}` : "";
        fileTabName.textContent = filename;
        fileExtension.textContent = extension || (languageSelect.value === "cpp" ? ".cpp" : ".py");
        editorStatusLanguage.textContent = languageSelect.value === "cpp" ? "C++" : "Python";
    }

    function setSaveState(state, label) {
        saveState.dataset.state = state;
        saveState.textContent = label;
        editorDirty.dataset.state = state;
        editorDirty.textContent = label;
    }

    function canDiscardChanges() {
        if (editorDirty.dataset.state !== "dirty" || (!codeEditor.value && !activeFileId)) return true;
        return window.confirm("Unsaved code hai. Bina save kiye aage badhna hai?");
    }

    function markDirty() {
        setSaveState("dirty", "Unsaved changes");
        updateGutter();
        updateFileMeta();
        analysisRequestId += 1;
        if (!codeEditor.value.trim()) {
            analysisResults.classList.add("hidden");
            analysisEmptyState.classList.remove("hidden");
            analysisEmptyState.querySelector("h3").textContent = "Khali plate pe kya scan karein?";
            analysisEmptyState.querySelector("p").textContent = "Code paste karein, phir instant scan — hints milenge, full solution nahi.";
            clearMessage(workbenchMessage);
            return;
        }
        analysisResults.classList.add("hidden");
        analysisEmptyState.classList.remove("hidden");
        analysisEmptyState.querySelector("h3").textContent = "Code update ho raha hai";
        analysisEmptyState.querySelector("p").textContent = "Bas ek moment — fresh static scan aa raha hai.";
        window.clearTimeout(analysisTimer);
        analysisTimer = window.setTimeout(() => analyzeCode(false), 700);
    }

    function goToLine(line) {
        if (!Number.isInteger(line) || line < 1) return;
        const source = codeEditor.value;
        const starts = [0];
        for (let index = 0; index < source.length; index += 1) {
            if (source[index] === "\n") starts.push(index + 1);
        }
        const start = starts[Math.min(line - 1, starts.length - 1)];
        const end = source.indexOf("\n", start);
        codeEditor.focus();
        codeEditor.setSelectionRange(start, end === -1 ? source.length : end);
        const lineHeight = parseFloat(getComputedStyle(codeEditor).lineHeight) || 20;
        codeEditor.scrollTop = Math.max(0, (line - 3) * lineHeight);
        editorGutter.scrollTop = codeEditor.scrollTop;
    }

    function lineButton(line) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "line-link";
        button.textContent = `L${line}`;
        button.title = `Go to line ${line}`;
        button.addEventListener("click", () => goToLine(line));
        return button;
    }

    function addLineDetails(parent, lines) {
        const visible = lines.slice(0, 6);
        visible.forEach((line, index) => {
            if (index) parent.append(document.createTextNode(", "));
            parent.append(lineButton(line));
        });
        if (lines.length > visible.length) {
            const details = document.createElement("details");
            const summary = document.createElement("summary");
            summary.textContent = `+${lines.length - visible.length} more lines`;
            details.append(summary);
            const extra = document.createElement("span");
            extra.className = "extra-lines";
            details.addEventListener("toggle", () => {
                if (!details.open || extra.childElementCount) return;
                lines.slice(visible.length).forEach((line, index) => {
                    if (index) extra.append(document.createTextNode(", "));
                    extra.append(lineButton(line));
                });
            });
            details.append(extra);
            parent.append(details);
        }
    }

    function renderConcepts(concepts) {
        conceptList.replaceChildren();
        if (!concepts.length) {
            const empty = document.createElement("li");
            empty.className = "coach-empty-line";
            empty.textContent = "Abhi koi listed construct detect nahi hua.";
            conceptList.append(empty);
            return;
        }
        concepts.forEach(concept => {
            const item = document.createElement("li");
            item.className = "concept-chip";
            const name = document.createElement("span");
            name.textContent = concept.name;
            item.append(name);
            if (concept.lines && concept.lines.length) {
                const lineMap = document.createElement("span");
                lineMap.className = "concept-lines";
                addLineDetails(lineMap, concept.lines);
                item.append(lineMap);
            }
            conceptList.append(item);
        });
    }

    function renderFindings(list, findings, emptyText, withSteps) {
        list.replaceChildren();
        if (!findings.length) {
            const empty = document.createElement("li");
            empty.textContent = emptyText;
            list.append(empty);
            return;
        }
        findings.forEach(finding => {
            const item = document.createElement("li");
            if (finding.line) {
                const line = document.createElement("span");
                line.className = "finding-line";
                line.append(lineButton(finding.line));
                item.append(line);
            }
            const title = document.createElement("div");
            title.className = "finding-title";
            title.textContent = finding.title || finding.description || "Static finding";
            item.append(title);
            if (finding.description && finding.title) {
                const description = document.createElement("div");
                description.textContent = finding.description;
                item.append(description);
            }
            if (withSteps && finding.steps && finding.steps.length) {
                const steps = document.createElement("ol");
                steps.className = "finding-steps";
                finding.steps.forEach(step => {
                    const stepItem = document.createElement("li");
                    stepItem.textContent = step;
                    steps.append(stepItem);
                });
                item.append(steps);
            }
            list.append(item);
        });
    }

    function renderAnalysisResults(analysis) {
        analysisEmptyState.classList.add("hidden");
        analysisResults.classList.remove("hidden");

        const line = analysis.error && analysis.error.line;
        if (analysis.error_type === "analysis_limit") {
            syntaxBanner.className = "syntax-banner invalid";
            syntaxBanner.textContent = `Static scan safe mode par ruk gaya: ${analysis.error.message}. Code ko chhote parts mein split karke try karein.`;
        } else if (analysis.language === "cpp" && analysis.syntax_checked === false) {
            syntaxBanner.className = `syntax-banner ${analysis.valid_syntax ? "valid" : "invalid"}`;
            syntaxBanner.textContent = analysis.valid_syntax
                ? "Structure clean — C++ compiler syntax check yahan nahi hota."
                : `Structure mein thoda drama · line ${line || "?"}: ${analysis.error.message}`;
        } else if (analysis.valid_syntax) {
            syntaxBanner.className = "syntax-banner valid";
            syntaxBanner.textContent = "Clean pass — lowkey textbook energy. Ab complexity pe nazar daalein.";
        } else {
            syntaxBanner.className = "syntax-banner invalid";
            syntaxBanner.textContent = `Syntax ne thoda drama kiya · line ${line || "?"}: ${analysis.error.message}. Hint dekhein aur khud fix karein.`;
        }

        const values = analysis.metrics || {};
        metrics.lines.textContent = values.total_lines ?? 0;
        metrics.functions.textContent = values.functions ?? 0;
        metrics.loops.textContent = values.loops ?? 0;
        metrics.conditionals.textContent = values.conditionals ?? 0;
        metrics.classes.textContent = values.classes ?? 0;
        metrics.complexity.textContent = values.cyclomatic_complexity ?? "—";
        metrics.recursions.textContent = values.recursions ?? 0;

        renderConcepts(analysis.concepts || []);
        const complexity = analysis.complexity || {};
        complexityTime.textContent = complexity.time || "Not estimated";
        complexitySpace.textContent = complexity.space || "Not estimated";
        renderFindings(complexitySpikes, complexity.spikes || [], "No clear complexity spike detected.", false);
        renderFindings(suggestionList, analysis.suggestions || [], "Abhi specific optimization cue nahi. Code lowkey clean lag raha hai.", true);
        renderFindings(hintList, analysis.hints || [], "Koi blocker nahi mila. Scene sorted — edge cases bhi check karein.", true);
        analysisSummary.textContent = analysis.summary || "";
    }

    async function analyzeCode(showStatus) {
        const source = codeEditor.value;
        if (!source.trim()) {
            analysisResults.classList.add("hidden");
            analysisEmptyState.classList.remove("hidden");
            analysisEmptyState.querySelector("h3").textContent = "Khali plate pe kya scan karein?";
            analysisEmptyState.querySelector("p").textContent = "Code paste karein, phir instant scan — hints milenge, full solution nahi.";
            if (showStatus) setMessage(workbenchMessage, "Editor khaali hai. Code paste karke scan karein.", true);
            return;
        }
        const requestId = ++analysisRequestId;
        btnAnalyzeRaw.disabled = true;
        const originalLabel = btnAnalyzeRaw.textContent;
        btnAnalyzeRaw.textContent = "Instant scan…";
        try {
            const result = await requestJson("/api/analyze-raw", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ content: source, language: languageSelect.value })
            });
            if (requestId !== analysisRequestId) return;
            renderAnalysisResults(result);
            if (showStatus) setMessage(workbenchMessage, "Instant scan ready — coach panel mein findings check karein.", false);
        } catch (error) {
            if (requestId === analysisRequestId) {
                setMessage(workbenchMessage, error.message, true);
                analysisEmptyState.classList.remove("hidden");
                analysisEmptyState.querySelector("h3").textContent = "Scan ruk gaya";
                analysisEmptyState.querySelector("p").textContent = "Network ya server issue lag raha hai. Connection check karke scan phir chalayein.";
            }
        } finally {
            btnAnalyzeRaw.disabled = false;
            btnAnalyzeRaw.textContent = originalLabel;
        }
    }

    function resetEditor() {
        window.clearTimeout(analysisTimer);
        analysisRequestId += 1;
        activeFileId = null;
        codeEditor.value = "";
        fileNameInput.value = languageSelect.value === "cpp" ? "main.cpp" : "main.py";
        analysisResults.classList.add("hidden");
        analysisEmptyState.classList.remove("hidden");
        analysisEmptyState.querySelector("h3").textContent = "Abhi kuch analyze nahi hua";
        analysisEmptyState.querySelector("p").textContent = "Code paste karein ya vault se file kholein. Phir instant scan — hints milenge, full solution nahi.";
        clearMessage(workbenchMessage);
        updateGutter();
        updateFileMeta();
        setSaveState("dirty", "New file");
        renderFileList([]);
    }

    function renderFileList(files) {
        fileList.replaceChildren();
        if (!files.length) {
            const empty = document.createElement("p");
            empty.className = "file-empty";
            empty.textContent = "Vault abhi khaali hai. New file banaiye, phir save — pack ho jayega.";
            fileList.append(empty);
            return;
        }
        files.forEach(file => {
            const row = document.createElement("div");
            row.className = "file-entry";
            const open = document.createElement("button");
            open.type = "button";
            open.className = `file-open${file.id === activeFileId ? " active" : ""}`;
            open.textContent = file.name;
            open.title = `Open ${file.name}`;
            open.addEventListener("click", () => loadFile(file.id));
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "file-delete";
            remove.textContent = "×";
            remove.title = `Delete ${file.name}`;
            remove.setAttribute("aria-label", `Delete ${file.name}`);
            remove.addEventListener("click", () => deleteFile(file.id));
            row.append(open, remove);
            fileList.append(row);
        });
    }

    async function loadWorkspaceDetails(workspaceId) {
        if (!workspaceId) {
            renderFileList([]);
            return;
        }
        try {
            const result = await requestJson(`/api/workspaces/${workspaceId}`);
            const workspace = result.workspace;
            vaultWorkspaceName.textContent = workspace.name;
            renderFileList(workspace.files || []);
        } catch (error) {
            setMessage(workbenchMessage, error.message, true);
        }
    }

    async function loadWorkspaces(preferredId) {
        try {
            const result = await requestJson("/api/workspaces");
            const workspaces = result.workspaces || [];
            workspaceSelect.replaceChildren();
            workspaces.forEach(workspace => {
                const option = document.createElement("option");
                option.value = workspace.id;
                option.textContent = `${workspace.name} · ${workspace.file_count} files`;
                workspaceSelect.append(option);
            });
            if (!workspaces.length) {
                activeWorkspaceId = null;
                vaultWorkspaceName.textContent = "No workspace yet";
                renderFileList([]);
                return;
            }
            const selected = workspaces.find(item => item.id === Number(preferredId))
                || workspaces.find(item => item.id === Number(activeWorkspaceId))
                || workspaces[0];
            activeWorkspaceId = selected.id;
            workspaceSelect.value = String(selected.id);
            await loadWorkspaceDetails(selected.id);
        } catch (error) {
            setMessage(workbenchMessage, error.message, true);
        }
    }

    async function loadFile(fileId) {
        if (!canDiscardChanges()) return;
        window.clearTimeout(analysisTimer);
        const requestId = ++analysisRequestId;
        try {
            const result = await requestJson(`/api/files/${fileId}`);
            if (requestId !== analysisRequestId) return;
            activeFileId = result.file.id;
            fileNameInput.value = result.file.name;
            languageSelect.value = result.file.language === "cpp" ? "cpp" : "python";
            codeEditor.value = result.file.content || "";
            updateGutter();
            updateFileMeta();
            renderAnalysisResults(result.analysis);
            setSaveState("saved", "Saved to vault");
            await loadWorkspaceDetails(activeWorkspaceId);
        } catch (error) {
            setMessage(workbenchMessage, error.message, true);
        }
    }

    async function deleteFile(fileId) {
        if (!window.confirm("File ko vault se hata dein? Wapas restore nahi hoga.")) return;
        try {
            await requestJson(`/api/files/${fileId}`, { method: "DELETE" });
            if (activeFileId === fileId) resetEditor();
            await loadWorkspaces(activeWorkspaceId);
            setMessage(workbenchMessage, "File vault se delete ho gayi — tata, bye-bye.", false);
        } catch (error) {
            setMessage(workbenchMessage, error.message, true);
        }
    }

    async function saveFile() {
        if (!activeWorkspaceId) {
            setMessage(workbenchMessage, "Pehle workspace choose ya create karein.", true);
            return;
        }
        const name = fileNameInput.value.trim();
        if (!name) {
            setMessage(workbenchMessage, "File ka naam khaali hai. .py ya .cpp filename daalein.", true);
            fileNameInput.focus();
            return;
        }
        const sourceFile = fileUploadInput.files && fileUploadInput.files[0];
        const originalLabel = btnSaveFile.textContent;
        btnSaveFile.disabled = true;
        btnSaveFile.textContent = "Saving…";
        clearMessage(workbenchMessage);
        window.clearTimeout(analysisTimer);
        analysisRequestId += 1;
        try {
            let result;
            const payload = {
                name,
                language: languageSelect.value,
                content: codeEditor.value
            };
            const url = activeFileId ? `/api/files/${activeFileId}` : `/api/workspaces/${activeWorkspaceId}/files`;
            result = await requestJson(url, {
                method: activeFileId ? "PUT" : "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            if (sourceFile) fileUploadInput.value = "";
            activeFileId = result.file.id;
            fileNameInput.value = result.file.name;
            languageSelect.value = result.file.language === "cpp" ? "cpp" : "python";
            codeEditor.value = result.file.content || "";
            updateGutter();
            updateFileMeta();
            renderAnalysisResults(result.analysis);
            setSaveState("saved", "Saved to vault");
            await loadWorkspaces(activeWorkspaceId);
            setMessage(workbenchMessage, "Vault mein pack ho gaya — code saved, scene sorted.", false);
        } catch (error) {
            setMessage(workbenchMessage, error.message, true);
            setSaveState("dirty", "Save failed");
        } finally {
            btnSaveFile.disabled = false;
            btnSaveFile.textContent = originalLabel;
        }
    }

    document.getElementById("showRegister").addEventListener("click", event => {
        event.preventDefault();
        clearMessage(loginMessage);
        showCard(registerCard);
    });

    document.getElementById("showLogin").addEventListener("click", event => {
        event.preventDefault();
        clearMessage(registerMessage);
        showCard(loginCard);
    });

    loginForm.addEventListener("submit", async event => {
        event.preventDefault();
        setMessage(loginMessage, "Login check ho raha hai…", false);
        try {
            const result = await requestJson("/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    email: document.getElementById("loginEmail").value,
                    password: document.getElementById("loginPassword").value
                })
            });
            showCard(workbenchCard);
            await loadWorkspaces();
            setMessage(workbenchMessage, `Welcome back, ${result.user.full_name}. Workspace ready — next kya scene?`, false);
        } catch (error) {
            setMessage(loginMessage, error.message, true);
        }
    });

    registerForm.addEventListener("submit", async event => {
        event.preventDefault();
        const password = document.getElementById("registerPassword").value;
        const confirmation = document.getElementById("confirmPassword").value;
        if (password !== confirmation) {
            setMessage(registerMessage, "Password match nahi hua. Dono fields same karke dobara try karein.", true);
            return;
        }
        setMessage(registerMessage, "Account ban raha hai…", false);
        try {
            const result = await requestJson("/api/auth/register", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    full_name: document.getElementById("fullName").value,
                    email: document.getElementById("registerEmail").value,
                    password,
                    confirm_password: confirmation
                })
            });
            showCard(workbenchCard);
            await loadWorkspaces(result.default_workspace_id);
            setMessage(workbenchMessage, "Account set. Naya adda ready — grind mode on.", false);
        } catch (error) {
            setMessage(registerMessage, error.message, true);
        }
    });

    document.getElementById("btnLogout").addEventListener("click", async () => {
        if (!canDiscardChanges()) return;
        try {
            await requestJson("/api/auth/logout", { method: "POST" });
            codeEditor.value = "";
            showCard(loginCard);
            setMessage(loginMessage, "Logout ho gaya. Milte hain phir.", false);
        } catch (error) {
            setMessage(workbenchMessage, error.message, true);
        }
    });

    document.getElementById("btnNewWorkspace").addEventListener("click", async () => {
        if (!canDiscardChanges()) return;
        const name = window.prompt("Naye workspace ka naam daalein:", "Project Workspace");
        if (!name || !name.trim()) return;
        try {
            const result = await requestJson("/api/workspaces", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: name.trim() })
            });
            await loadWorkspaces(result.workspace.id);
            resetEditor();
            setMessage(workbenchMessage, "Naya adda taiyar. Ab code add karein.", false);
        } catch (error) {
            setMessage(workbenchMessage, error.message, true);
        }
    });

    workspaceSelect.addEventListener("change", async () => {
        if (!canDiscardChanges()) {
            workspaceSelect.value = String(activeWorkspaceId || "");
            return;
        }
        activeWorkspaceId = Number(workspaceSelect.value) || null;
        activeFileId = null;
        resetEditor();
        await loadWorkspaceDetails(activeWorkspaceId);
    });

    document.getElementById("btnNewFile").addEventListener("click", () => {
        if (canDiscardChanges()) resetEditor();
    });
    btnAnalyzeRaw.addEventListener("click", () => analyzeCode(true));
    btnSaveFile.addEventListener("click", saveFile);

    languageSelect.addEventListener("change", () => {
        const oldExtension = /\.(py|cpp|h|hpp)$/i;
        const nextExtension = languageSelect.value === "cpp" ? ".cpp" : ".py";
        if (oldExtension.test(fileNameInput.value)) {
            fileNameInput.value = fileNameInput.value.replace(oldExtension, nextExtension);
        } else if (fileNameInput.value.trim()) {
            fileNameInput.value = `${fileNameInput.value.trim()}${nextExtension}`;
        }
        updateFileMeta();
        markDirty();
    });

    fileNameInput.addEventListener("input", () => {
        const extension = fileNameInput.value.split(".").pop().toLowerCase();
        const inferredLanguage = ["cpp", "h", "hpp"].includes(extension) ? "cpp"
            : extension === "py" ? "python" : languageSelect.value;
        const languageChanged = inferredLanguage !== languageSelect.value;
        if (languageChanged) languageSelect.value = inferredLanguage;
        updateFileMeta();
        if (activeFileId || languageChanged) markDirty();
    });

    fileUploadInput.addEventListener("change", () => {
        const file = fileUploadInput.files && fileUploadInput.files[0];
        if (!file) return;
        if (!canDiscardChanges()) {
            fileUploadInput.value = "";
            return;
        }
        if (file.size > 2 * 1024 * 1024) {
            fileUploadInput.value = "";
            setMessage(workbenchMessage, "File 2MB limit se badi hai. Smaller version upload karein.", true);
            return;
        }
        const extension = file.name.split(".").pop().toLowerCase();
        if (!["py", "cpp", "h", "hpp"].includes(extension)) {
            fileUploadInput.value = "";
            setMessage(workbenchMessage, "Sirf .py, .cpp, .h ya .hpp files supported hain.", true);
            return;
        }
        fileNameInput.value = file.name;
        languageSelect.value = ["cpp", "h", "hpp"].includes(extension) ? "cpp" : "python";
        updateFileMeta();
        const reader = new FileReader();
        reader.onload = event => {
            codeEditor.value = typeof event.target.result === "string" ? event.target.result : "";
            activeFileId = null;
            updateGutter();
            markDirty();
        };
        reader.onerror = () => {
            fileUploadInput.value = "";
            setMessage(workbenchMessage, "File read nahi hui. UTF-8 text file ke saath dobara try karein.", true);
        };
        reader.readAsText(file);
    });

    codeEditor.addEventListener("input", markDirty);
    codeEditor.addEventListener("scroll", () => {
        editorGutter.scrollTop = codeEditor.scrollTop;
    });
    codeEditor.addEventListener("keydown", event => {
        if (event.key === "Tab") {
            event.preventDefault();
            const start = codeEditor.selectionStart;
            const end = codeEditor.selectionEnd;
            codeEditor.setRangeText("    ", start, end, "end");
            markDirty();
        } else if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
            event.preventDefault();
            analyzeCode(true);
        } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
            event.preventDefault();
            saveFile();
        }
    });

    async function checkSession() {
        try {
            const result = await requestJson("/api/auth/me");
            if (result.authenticated) {
                showCard(workbenchCard);
                await loadWorkspaces();
            } else {
                showCard(loginCard);
            }
        } catch (error) {
            showCard(loginCard);
            if (!error.message.includes("Session expire") && !error.message.includes("Authentication required")) {
                setMessage(loginMessage, error.message, true);
            }
        }
    }

    updateGutter();
    updateFileMeta();
    checkSession();
});
