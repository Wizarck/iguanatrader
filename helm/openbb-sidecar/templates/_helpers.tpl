{{/*
_helpers.tpl — openbb-sidecar Helm Chart template helpers.
*/}}

{{- define "openbb-sidecar.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "openbb-sidecar.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "openbb-sidecar.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "openbb-sidecar.namespace" -}}
{{ .Values.namespace | default "iguanatrader" }}
{{- end }}

{{/* Labels applied to every resource. */}}
{{- define "openbb-sidecar.labels" -}}
helm.sh/chart: {{ include "openbb-sidecar.chart" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/name: {{ include "openbb-sidecar.name" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- range $k, $v := .Values.extraLabels }}
{{ $k }}: {{ $v | quote }}
{{- end }}
{{- end }}

{{- define "openbb-sidecar.selectorLabels" -}}
app.kubernetes.io/name: {{ include "openbb-sidecar.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/* Image reference: prefer digest pin, fall back to tag. */}}
{{- define "openbb-sidecar.image" -}}
{{- if .Values.image.digest -}}
{{ .Values.image.repository }}@{{ .Values.image.digest }}
{{- else -}}
{{ .Values.image.repository }}:{{ .Values.image.tag | default "latest" }}
{{- end -}}
{{- end }}
