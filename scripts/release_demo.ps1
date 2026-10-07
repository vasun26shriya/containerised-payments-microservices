param(
    [string]$Kubectl = 'kubectl',
    [string]$Helm = 'helm',
    [string]$Docker = 'docker',
    [string]$Context = 'payments',
    [string]$Namespace = 'payments-demo',
    [string]$Evidence = '.run/release-demo'
)
$ErrorActionPreference = 'Stop'
function Invoke-Checked([string]$Tool, [string[]]$Arguments) {
    & $Tool @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Tool failed" }
}
if ($Namespace -notmatch '^[a-z][a-z0-9-]+$' -or $Context -notmatch '^[a-z][a-z0-9-]+$') { throw 'Use a valid dedicated namespace and Minikube context' }
# Refuse to modify a pre-existing namespace: this exercise owns only its new lab.
& $Kubectl --context=$Context get namespace $Namespace -o name 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { throw "Namespace $Namespace already exists; select a fresh lab namespace" }
New-Item -ItemType Directory -Path $Evidence -Force | Out-Null
$transferPath = Join-Path $Evidence 'api-images.tar'
foreach ($service in @('orders','payments')) {
    Invoke-Checked $Docker @('build','-f',"services/$service.Dockerfile",'-t',"payments-$($service):portfolio-v1",'.')
    Invoke-Checked $Docker @('tag',"payments-$($service):portfolio-v1","payments-$($service):portfolio-v2")
}
Invoke-Checked $Docker @('save','-o',$transferPath,'payments-orders:portfolio-v1','payments-orders:portfolio-v2','payments-payments:portfolio-v1','payments-payments:portfolio-v2')
Invoke-Checked $Docker @('cp',$transferPath,"${Context}:/var/portfolio-images.tar")
Invoke-Checked $Docker @('exec',$Context,'docker','load','-i','/var/portfolio-images.tar')
Invoke-Checked $Kubectl @("--context=$Context",'create','namespace',$Namespace)
Invoke-Checked $Kubectl @("--context=$Context",'-n',$Namespace,'create','secret','generic','payments-runtime','--from-literal=MONGO_URI=mongodb://portfolio-mongo:27017')
$common = @('portfolio','helm/payments',"--kube-context=$Context",'-n',$Namespace,'-f','helm/payments/values-dev.yaml','--wait','--atomic','--timeout','5m')
$forwardProcesses = @()
function Start-ApiForwards {
    foreach ($process in $script:forwardProcesses) { if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit() } }
    $script:forwardProcesses = @()
    foreach ($service in @('orders','payments')) {
        $port = if ($service -eq 'orders') {'38000:8000'} else {'38001:8000'}
        $script:forwardProcesses += Start-Process -FilePath (Get-Command $Kubectl).Source -ArgumentList @("--context=$Context",'-n',$Namespace,'port-forward',"svc/portfolio-$service",$port) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Evidence "$service-forward.log") -RedirectStandardError (Join-Path $Evidence "$service-forward-error.log")
    }
}
try {
    Invoke-Checked $Helm (@('upgrade','--install') + $common + @('--set','services.orders.tag=portfolio-v1','--set','services.payments.tag=portfolio-v1'))
    Start-ApiForwards
    Invoke-Checked 'python' @('scripts/smoke_stack.py','--orders','http://127.0.0.1:38000','--payments','http://127.0.0.1:38001','--evidence',"$Evidence/install.json")
    Invoke-Checked $Helm (@('upgrade') + $common + @('--set','services.orders.tag=portfolio-v2','--set','services.payments.tag=portfolio-v2'))
    Start-ApiForwards
    Invoke-Checked 'python' @('scripts/smoke_stack.py','--orders','http://127.0.0.1:38000','--payments','http://127.0.0.1:38001','--previous',"$Evidence/install.json",'--evidence',"$Evidence/upgrade.json")
    Invoke-Checked $Helm @('rollback','portfolio','1',"--kube-context=$Context",'-n',$Namespace,'--wait','--timeout','5m')
    Start-ApiForwards
    Invoke-Checked 'python' @('scripts/smoke_stack.py','--orders','http://127.0.0.1:38000','--payments','http://127.0.0.1:38001','--previous',"$Evidence/install.json",'--evidence',"$Evidence/rollback.json")
    & $Helm history portfolio --kube-context=$Context -n $Namespace | Set-Content (Join-Path $Evidence 'helm-history.txt')
    Write-Output "PASS: dedicated lab install, upgrade, rollback and persisted order. Lab namespace retained: $Namespace"
} finally {
    foreach ($process in $forwardProcesses) { if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit() } }
    Invoke-Checked $Docker @('exec',$Context,'rm','-f','/var/portfolio-images.tar')
}
