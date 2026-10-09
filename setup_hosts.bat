@echo off
chcp 65001 >nul
echo ========================================================
echo   FocusGuard - Windows hosts ファイル権限設定ツール
echo ========================================================
echo.
echo このバッチファイルを「管理者として実行」することで、
echo FocusGuard が Windows の hosts ファイルを直接更新し、
echo PC起動直後（アプリ起動前の隙間時間）から1秒の隙もなく
echo 全ブラウザ・全通信で X などの指定サイトを完全遮断できるようになります。
echo.

openfiles >nul 2>&1
if %errorlevel% neq 0 (
    echo [エラー] 管理者権限で実行されていません。
    echo 右クリックして「管理者として実行」を選択してください。
    echo.
    pause
    exit /b 1
)

echo hosts ファイルにユーザー変更権限を付与しています...
icacls "%SystemRoot%\System32\drivers\etc\hosts" /grant Users:(M) >nul 2>&1

if %errorlevel% equ 0 (
    echo.
    echo [成功] 権限の付与が完了しました！
    echo FocusGuard の hosts ファイル直接連携機能が有効になりました。
) else (
    echo.
    echo [失敗] 権限の付与に失敗しました。
)

echo.
pause
