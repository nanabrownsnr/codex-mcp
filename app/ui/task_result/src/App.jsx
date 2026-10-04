// Render the structured result returned by run_task.
import { useCallback, useState } from "react";
import {
    useApp,
    useDocumentTheme,
    useHostFonts,
    useHostStyleVariables,
} from "@modelcontextprotocol/ext-apps/react";

export default function TaskResultApp() {
    const [result, setResult] = useState(null);

    const onAppCreated = useCallback((createdApp) => {
        createdApp.ontoolresult = (toolResult) => {
            setResult(toolResult.structuredContent ?? null);
        };
    }, []);

    const { app, isConnected, error } = useApp({
        appInfo: { name: "twynity-codex-harness", version: "1.0.0" },
        capabilities: {},
        onAppCreated,
        autoResize: true,
    });

    useHostStyleVariables(app, app?.getHostContext());
    useHostFonts(app, app?.getHostContext());
    const theme = useDocumentTheme();

    return (
        <main className="card" aria-live="polite" data-host-theme={theme}>
            <p className="eyebrow">Twynity coding task</p>
            <h1>{result?.status === "completed" ? "Task complete" : "Task result"}</h1>
            <dl className="task-details">
                <dt>Project</dt><dd>{result?.project_name ?? "Waiting for a task"}</dd>
                <dt>Status</dt><dd>{result?.status ?? (error ? "Connection error" : isConnected ? "Ready" : "Connecting")}</dd>
                <dt>Branch</dt><dd>{result?.branch ?? "—"}</dd>
                <dt>Commit</dt><dd>{result?.commit ?? (result?.published ? "Published" : "No new commit")}</dd>
            </dl>
            <p className="response">
                {result?.response ?? error?.message ?? "Call run_task to work on this Twyn's configured repository."}
            </p>
        </main>
    );
}
