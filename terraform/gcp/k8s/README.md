# Kubernetes manifests

Manifests for deploying 4THealth onto the cluster this Terraform creates. Adapted from
`docs/kubernetes-gcp.md` in the app repo (`~/code/github/web/4thealth`), with fixes noted below.
Not yet tested against a live cluster.

| File | Purpose |
|---|---|
| `00-namespace.yaml` | `4thealth` namespace |
| `10-pvc.yaml` | 5Gi PVC for certs and JSON state |
| `20-deployment.yaml` | App pod, plus an init container that seeds the PVC |
| `30-service.yaml` | `ClusterIP` Service for `kubectl port-forward` testing |
| _(Terraform output)_ `public_lb_manifest` | Temporary public HTTPS Service restricted to your IP; see the top-level README |
| `internal-lb/service.yaml` | Internal load balancer Service for real (VPN) access; not applied by default |

## Deploy and test

Run from this repo after `terraform apply` and the import steps in the top-level README.

```bash
# 1. Connect kubectl
$(terraform output -raw configure_kubectl)

# 2. Build and push the image (run in the app repo; Apple Silicon needs --platform)
gcloud auth configure-docker us-central1-docker.pkg.dev
cd ~/code/github/web/4thealth
REPO=us-central1-docker.pkg.dev/t-application-environment/four-t-health
docker build --platform linux/amd64 -t $REPO/app:test .
docker push $REPO/app:test
cd -

# 3. Namespace, then the Secret BEFORE the pod (the app refuses to start without SECRET_KEY)
kubectl apply -f k8s/00-namespace.yaml
kubectl create secret generic 4thealth-env \
  --from-env-file=$HOME/code/github/web/4thealth/.env -n 4thealth

# 4. Everything else
kubectl apply -f k8s/10-pvc.yaml -f k8s/20-deployment.yaml -f k8s/30-service.yaml
kubectl get pods -n 4thealth -w

# 5. Create the first admin, then browse (HTTPS, self-signed: accept the warning)
kubectl exec -it -n 4thealth deploy/4thealth -- python manage_users.py add admin --role admin
kubectl port-forward -n 4thealth svc/fourthealth 8443:443   # https://localhost:8443
```

The `.env` needs a real `SECRET_KEY` (`python manage_users.py secret`). If the app should reach
FortiManager from the cluster, `FMG_PRIMARY_HOST` must be reachable via Cloud NAT.

Debugging: `kubectl describe pod -n 4thealth -l app=4thealth`,
`kubectl logs -n 4thealth deploy/4thealth`, and
`kubectl logs -n 4thealth deploy/4thealth -c seed-data` for the init container.

## Differences from the guide

- **Service is named `fourthealth`.** Service names must start with a letter.
- **Image path** uses this repo's registry (`four-t-health`) and the `test` tag.
- **Init container seeds the PVC.** The guide copies certs and data in after the pod starts, but
  gunicorn needs `certs/cert.pem` at startup and `subPath` mounts of missing files become
  directories. The init container generates a self-signed cert and creates empty-but-valid JSON
  files only where none exist, so later `kubectl cp` of real data is not overwritten on restart.
- **`fsGroup: 2000`** with a chgrp in the init container, so the non-root app user can write.
- **Autopilot resource requests** (500m CPU, 1Gi) are set explicitly.

## Known risks (untested)

- The empty seed files (`{}` / `[]`) are guesses at valid minimal shapes. If the app errors on
  startup, check the logs and `kubectl cp` the real `*.example.json` files in.
- The init image `alpine/openssl` is pulled from Docker Hub through Cloud NAT, which can be rate
  limited.
- Files mounted with `subPath` can't be replaced by rename, so if the app saves JSON through a
  temp-file-and-rename pattern, those writes may fail with "Device or resource busy".

## Cleanup

Delete the workload before `terraform destroy`; deleting the namespace also removes the PVC and
its disk:

```bash
kubectl delete namespace 4thealth
```
