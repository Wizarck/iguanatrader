{{/*
Common labels and helpers for iguanatrader-stack.
*/}}

{{- define "iguanatrader.fullname" -}}
{{- printf "%s" (include "iguanatrader.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "iguanatrader.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "iguanatrader.labels" -}}
app.kubernetes.io/name: {{ include "iguanatrader.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: "{{ .Chart.AppVersion }}"
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: "{{ .Chart.Name }}-{{ .Chart.Version }}"
{{- end -}}

{{- define "iguanatrader.apiImage" -}}
{{- $tag := default .Chart.AppVersion .Values.image.api.tag -}}
{{- printf "%s:%s" .Values.image.api.repository $tag -}}
{{- end -}}

{{- define "iguanatrader.openbbImage" -}}
{{- $tag := default .Chart.AppVersion .Values.image.openbb.tag -}}
{{- printf "%s:%s" .Values.image.openbb.repository $tag -}}
{{- end -}}
