const vscode = require('vscode');
const path = require('path');
const { execSync, exec } = require('child_process');
const fs = require('fs');
let LanguageClient, TransportKind;
try {
    ({ LanguageClient, TransportKind } = require('vscode-languageclient/node'));
} catch (e) {
    // LSP 클라이언트 없으면 무시 — 기본 기능은 동작
}

let diagnosticCollection;
let outputChannel;
let lspClient;

function activate(context) {
    diagnosticCollection = vscode.languages.createDiagnosticCollection('geul');
    outputChannel = vscode.window.createOutputChannel('글 언어');

    // 컴파일러 경로 탐색 (네이티브컴파일러 우선)
    function findToolPath() {
        const config = vscode.workspace.getConfiguration('geul');
        const configPath = config.get('compilerPath') || config.get('toolPath');
        if (configPath && fs.existsSync(configPath)) return configPath;

        // install.ps1 기본 설치 경로
        const installDir = path.join(process.env.LOCALAPPDATA || '', 'geul-lang', 'bin');
        for (const name of ['\uB124\uC774\uD2F0\uBE0C\uCEF4\uD30C\uC77C\uB7EC.exe', 'geulc.exe']) {
            const p = path.join(installDir, name);
            if (fs.existsSync(p)) return p;
        }

        // 확장 디렉토리 내
        for (const name of ['\uB124\uC774\uD2F0\uBE0C\uCEF4\uD30C\uC77C\uB7EC.exe', 'geulc.exe']) {
            const p = path.join(context.extensionPath, 'bin', name);
            if (fs.existsSync(p)) return p;
        }

        // PATH에서 탐색
        try {
            const result = execSync('where geulc.exe', { encoding: 'utf8', timeout: 5000 });
            const found = result.trim().split('\n')[0].trim();
            if (found && fs.existsSync(found)) return found;
        } catch (e) {}

        return null;
    }

    function isNativeCompiler(toolPath) {
        return toolPath && !toolPath.includes('\uAE00\uB3C4\uAD6C');
    }

    // 오류 파싱: "파일:줄:열: 오류: 메시지"
    function parseErrors(output, filePath) {
        const diagnostics = [];
        const lines = output.split('\n');
        for (const line of lines) {
            const match = line.match(/(\d+):(\d+):\s*오류:\s*(.+)/);
            if (match) {
                const lineNum = Math.max(0, parseInt(match[1]) - 1);
                const colNum = Math.max(0, parseInt(match[2]) - 1);
                const message = match[3].trim();
                const range = new vscode.Range(lineNum, colNum, lineNum, colNum + 10);
                const diagnostic = new vscode.Diagnostic(range, message, vscode.DiagnosticSeverity.Error);
                diagnostics.push(diagnostic);
            }
        }
        const uri = vscode.Uri.file(filePath);
        diagnosticCollection.set(uri, diagnostics);
        return diagnostics.length;
    }

    // 명령 실행
    function runCommand(command) {
        const editor = vscode.window.activeTextEditor;
        if (!editor || !editor.document.fileName.endsWith('.글')) {
            vscode.window.showErrorMessage('글 파일을 열어주세요 (.글)');
            return;
        }

        // 저장 먼저
        editor.document.save().then(() => {
            const filePath = editor.document.fileName;
            const toolPath = findToolPath();

            if (!toolPath) {
                vscode.window.showErrorMessage(
                    '컴파일러를 찾을 수 없습니다. install.ps1로 설치하거나 설정에서 경로를 지정하세요.',
                    '설정 열기'
                ).then(selection => {
                    if (selection === '설정 열기') {
                        vscode.commands.executeCommand('workbench.action.openSettings', 'geul.compilerPath');
                    }
                });
                return;
            }

            diagnosticCollection.clear();
            const native = isNativeCompiler(toolPath);

            if (command === '실행') {
                // 터미널에서 컴파일 + 실행
                let terminal = vscode.window.terminals.find(t => t.name === '글 실행');
                if (!terminal) {
                    terminal = vscode.window.createTerminal('글 실행');
                }
                terminal.show();
                if (native) {
                    const exePath = filePath.replace(/\.글$/, '.exe');
                    // 기존 exe 삭제 → 컴파일 → exe 존재 시에만 실행
                    terminal.sendText(`chcp 65001 | Out-Null; Remove-Item "${exePath}" -ErrorAction SilentlyContinue; & "${toolPath}" "${filePath}" 2>&1; if (Test-Path "${exePath}") { & "${exePath}" } else { Write-Host "컴파일 실패" -ForegroundColor Red }`);
                } else {
                    terminal.sendText(`& "${toolPath}" 실행 "${filePath}"`);
                }
            } else if (command === '빌드') {
                outputChannel.clear();
                outputChannel.show();
                outputChannel.appendLine(`빌드 중: ${path.basename(filePath)}`);

                const buildCmd = native ? `"${toolPath}" "${filePath}"` : `"${toolPath}" 빌드 "${filePath}"`;
                exec(buildCmd, { encoding: 'utf8' }, (error, stdout, stderr) => {
                    if (stderr) {
                        outputChannel.appendLine(stderr);
                        const errCount = parseErrors(stderr, filePath);
                        if (errCount > 0) {
                            vscode.window.showErrorMessage(`빌드 실패: ${errCount}개 오류`);
                        } else if (stderr.includes('빌드 완료')) {
                            vscode.window.showInformationMessage(stderr.trim());
                        }
                    }
                    if (stdout) outputChannel.appendLine(stdout);
                });
            } else if (command === '검사') {
                outputChannel.clear();
                outputChannel.show();

                const checkCmd = native ? `"${toolPath}" --dump-ir "${filePath}"` : `"${toolPath}" 검사 "${filePath}"`;
                exec(checkCmd, { encoding: 'utf8' }, (error, stdout, stderr) => {
                    const allOutput = (stderr || '') + (stdout || '');
                    outputChannel.appendLine(allOutput);
                    const errCount = parseErrors(allOutput, filePath);

                    if (errCount > 0) {
                        vscode.window.showErrorMessage(`${errCount}개 오류 발견`);
                    } else {
                        vscode.window.showInformationMessage('검사 완료: 오류 없음 ✓');
                        diagnosticCollection.clear();
                    }
                });
            }
        });
    }

    // 명령 등록
    context.subscriptions.push(
        vscode.commands.registerCommand('geul.run', () => runCommand('실행')),
        vscode.commands.registerCommand('geul.build', () => runCommand('빌드')),
        vscode.commands.registerCommand('geul.check', () => runCommand('검사')),
        diagnosticCollection,
        outputChannel
    );

    // F5는 keybinding → geul.run 명령으로 직접 연결됨 (package.json)

    // ── LSP 클라이언트 시작 ──
    const lspServerModule = path.join(context.extensionPath, 'server', 'server.js');
    if (LanguageClient && fs.existsSync(lspServerModule)) {
        const serverOptions = {
            run:   { module: lspServerModule, transport: TransportKind.ipc },
            debug: { module: lspServerModule, transport: TransportKind.ipc },
        };
        const clientOptions = {
            documentSelector: [{ scheme: 'file', language: 'geul' }],
        };
        lspClient = new LanguageClient(
            'geulLanguageServer',
            '글 Language Server',
            serverOptions,
            clientOptions
        );
        lspClient.start();
        context.subscriptions.push({ dispose: () => lspClient && lspClient.stop() });
        outputChannel.appendLine('글 LSP 클라이언트 시작됨');
    } else {
        // LSP 서버 없으면 기존 저장 시 자동 검사 사용
        vscode.workspace.onDidSaveTextDocument(document => {
            if (document.languageId === 'geul') {
                const toolPath = findToolPath();
                if (!toolPath) return;

                exec(`"${toolPath}" 검사 "${document.fileName}"`, { encoding: 'utf8' }, (error, stdout, stderr) => {
                    const allOutput = (stderr || '') + (stdout || '');
                    parseErrors(allOutput, document.fileName);
                    if (!allOutput.includes('오류')) {
                        diagnosticCollection.delete(document.uri);
                    }
                });
            }
        });
    }
}

function deactivate() {
    if (lspClient) {
        return lspClient.stop();
    }
}

module.exports = { activate, deactivate };
