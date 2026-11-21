// Stark World Engine Runtime - data assets. The editor build script creates one asset per quest / dialogue / item / NPC / enemy /
// level under /Game/Stark/Data and a UStarkGameData that lists them. Designers edit these assets; the runtime reads
// them (or Content/Stark/Data/stark_game_ue.json when the assets were not built yet).
// UDataAsset: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Engine/UDataAsset
// UPrimaryDataAsset: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Engine/UPrimaryDataAsset
// Data assets overview: https://dev.epicgames.com/documentation/en-us/unreal-engine/data-assets-in-unreal-engine
#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "StarkTypes.h"
#include "StarkDataAssets.generated.h"

class USoundBase;

UCLASS(BlueprintType)
class STARKRUNTIME_API UStarkItemAsset : public UDataAsset
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") FStarkItemDef Item;
	/** Fill from one item object of stark_game_ue.json (used by the editor build script). */
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") bool ImportJson(const FString& Json);
};

UCLASS(BlueprintType)
class STARKRUNTIME_API UStarkEnemyAsset : public UDataAsset
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") FStarkEnemyDef Enemy;
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") bool ImportJson(const FString& Json);
};

UCLASS(BlueprintType)
class STARKRUNTIME_API UStarkNpcAsset : public UDataAsset
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") FStarkNpcDef Npc;
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") bool ImportJson(const FString& Json);
};

UCLASS(BlueprintType)
class STARKRUNTIME_API UStarkQuestAsset : public UDataAsset
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") FStarkQuestDef Quest;
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") bool ImportJson(const FString& Json);
};

UCLASS(BlueprintType)
class STARKRUNTIME_API UStarkDialogueAsset : public UDataAsset
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") FStarkDialogueDef Dialogue;
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") bool ImportJson(const FString& Json);
};

UCLASS(BlueprintType)
class STARKRUNTIME_API UStarkLevelAsset : public UDataAsset
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") FStarkLevelDef Level;
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") bool ImportJson(const FString& Json);
};

/** The game: rules + every quest, dialogue, item, NPC, enemy and level asset. One per project at
 *  /Game/Stark/Data/DA_StarkGame (the runtime loads it from there). */
UCLASS(BlueprintType)
class STARKRUNTIME_API UStarkGameData : public UPrimaryDataAsset
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") FString Title;
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") FString Author;
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine", meta = (MultiLine = true)) FString Story;
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") FString SaveKey;
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") TArray<FString> Minors;
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") FStarkRulesDef Rules;
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") TArray<TObjectPtr<UStarkItemAsset>> Items;
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") TArray<TObjectPtr<UStarkEnemyAsset>> Enemies;
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") TArray<TObjectPtr<UStarkQuestAsset>> Quests;
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") TArray<TObjectPtr<UStarkDialogueAsset>> Dialogues;
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") TArray<TObjectPtr<UStarkNpcAsset>> Npcs;
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") TArray<TObjectPtr<UStarkLevelAsset>> Levels;
	/** Sound effects by name (jump, coin, hit, laser, boom, power, quest, levelup, door, portal, talk, magic). */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Stark World Engine") TMap<FString, TSoftObjectPtr<USoundBase>> Sounds;

	/** Fill Title / Author / Story / SaveKey / Rules from the whole stark_game_ue.json. */
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") bool ImportHeaderJson(const FString& Json);
	/** Everything above as one struct (what the runtime plays). */
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") FStarkGameDef BuildGameDef() const;
};
