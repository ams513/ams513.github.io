// Stark World Engine Runtime - game mode (hero pawn, HUD, level start) and a Canvas HUD (no widget assets needed): HUD bars,
// quest tracker, toasts, interaction prompt, dialogue with numbered answers, quest log, bag, save menu, boss bar.
// AGameModeBase: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/GameFramework/AGameModeBase
// AHUD: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/GameFramework/AHUD
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "GameFramework/HUD.h"
#include "StarkGameMode.generated.h"

UCLASS()
class STARKRUNTIME_API AStarkGameMode : public AGameModeBase
{
	GENERATED_BODY()
public:
	AStarkGameMode();
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;
private:
	void NotifyLevelReady();
};

UCLASS()
class STARKRUNTIME_API AStarkHUD : public AHUD
{
	GENERATED_BODY()
public:
	virtual void DrawHUD() override;
	/** Big centred title (level names, victory). */
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void ShowBigText(const FString& Title, const FString& Subtitle, float Seconds);
	/** Boss name + health fraction; Fraction < 0 hides the bar. */
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void SetBossBar(const FString& Name, float Fraction);
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void AddToast(const FString& Message, const FString& Kind);
private:
	void Panel(float X, float Y, float W, float H);
	float Line(const FString& Text, float X, float Y, const FLinearColor& Color, float Scale = 1.f, bool bLarge = false);
	TArray<TPair<FString, float>> Toasts;
	FString BigTitle, BigSub;
	float BigT = 0.f;
	FString BossName;
	float BossFraction = -1.f;
	double LastTime = 0.0;
};
