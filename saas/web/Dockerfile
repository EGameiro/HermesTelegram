# Painel Hermes SaaS (.NET 8) — imagem para o VPS (Dokploy/Kestrel, sem IIS).
# Build context esperado: saas/web  (o diretório deste Dockerfile).

# ---- build ----
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY HermesSaaS.Web.csproj ./
RUN dotnet restore HermesSaaS.Web.csproj
COPY . ./
RUN dotnet publish HermesSaaS.Web.csproj -c Release -o /app /p:UseAppHost=false

# ---- runtime ----
FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app ./
# Kestrel escuta na 8080 (o Traefik do Dokploy faz o proxy + HTTPS).
ENV ASPNETCORE_URLS=http://+:8080
ENV ASPNETCORE_ENVIRONMENT=Production
EXPOSE 8080
ENTRYPOINT ["dotnet", "HermesSaaS.Web.dll"]
