using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

internal static class FastViewshedLauncher
{
    [STAThread]
    private static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string logs = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "FastViewshed", "Logs");
        Directory.CreateDirectory(logs);
        string logPath = Path.Combine(logs, "launcher.log");
        try
        {
            using (StreamWriter log = new StreamWriter(logPath, true, Encoding.UTF8))
            {
                log.AutoFlush = true;
                log.WriteLine(DateTime.Now.ToString("s") + " Starting " + root);
                ProcessStartInfo start = new ProcessStartInfo();
                start.FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "cmd.exe");
                start.Arguments = "/d /s /c \"\"" + Path.Combine(root, "Run_Fast_Viewshed.bat") + "\" --launcher\"";
                start.WorkingDirectory = root;
                start.UseShellExecute = false;
                start.CreateNoWindow = true;
                start.RedirectStandardOutput = true;
                start.RedirectStandardError = true;
                if (args.Length == 2 && args[0] == "--smoke-test")
                    start.EnvironmentVariables["FAST_VIEWSHED_SMOKE_REPORT"] = Path.GetFullPath(args[1]);
                using (Process process = new Process())
                {
                    process.StartInfo = start;
                    process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) lock (log) log.WriteLine(e.Data); };
                    process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) lock (log) log.WriteLine(e.Data); };
                    process.Start();
                    process.BeginOutputReadLine();
                    process.BeginErrorReadLine();
                    process.WaitForExit();
                    int code = process.ExitCode;
                    if (code != 0) throw new Exception("Fast Viewshed could not start. Exit code: " + code);
                }
            }
            return 0;
        }
        catch (Exception error)
        {
            File.AppendAllText(logPath, error.ToString() + Environment.NewLine, Encoding.UTF8);
            MessageBox.Show("Unable to start Fast Viewshed.\n\n" + error.Message + "\n\nLog: " + logPath,
                            "Fast Viewshed", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
