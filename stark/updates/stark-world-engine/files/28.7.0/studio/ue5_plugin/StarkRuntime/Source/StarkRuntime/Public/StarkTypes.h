// Stark World Engine Runtime - game data types. Property names match Content/Stark/Data/stark_game_ue.json (written by
// Stark World Engine), so FJsonObjectConverter fills them directly.
// USTRUCT / UPROPERTY: https://dev.epicgames.com/documentation/en-us/unreal-engine/structs-in-unreal-engine
// FJsonObjectConverter: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/JsonUtilities/FJsonObjectConverter
#pragma once

#include "CoreMinimal.h"
#include "StarkTypes.generated.h"

/** Stark World Engine plan coordinates are metres with y up and x/z on the ground; Unreal is centimetres with Z up.
 *  The mapping keeps the layout un-mirrored: UE X = -z, UE Y = x, UE Z = y. Actor yaw (UE) = plan yaw. */
inline FVector StarkToUE(float X, float Y, float Z) { return FVector(-Z * 100.f, X * 100.f, Y * 100.f); }
inline FVector2D UEToStarkXZ(const FVector& V) { return FVector2D(V.Y / 100.f, -V.X / 100.f); }

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkCondition
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Has;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 N = 1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Lacks;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Done;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Active;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString NotStarted;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Flag;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 MinLevel = 0;
};

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkAction
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Start;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Complete;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Advance;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FString> Give;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Take;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 TakeCount = 1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Gold = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Xp = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Flag;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") bool Heal = false;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") bool Win = false;
};

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkChoice
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Text;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Goto;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") bool End = false;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") bool HasRequires = false;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FStarkCondition Requires;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FStarkAction Action;
};

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkDialogueNode
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Id;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Speaker;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine", meta = (MultiLine = true)) FString Text;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Next;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FStarkAction Action;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FStarkChoice> Choices;
};

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkDialogueBranch
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") bool HasRequires = false;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FStarkCondition Requires;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Node;
};

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkDialogueDef
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Id;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Start;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FStarkDialogueBranch> Branches;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FStarkDialogueNode> Nodes;
};

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkQuestStep
{
	GENERATED_BODY()
	/** collect | defeat | talk | reach | escort */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Type;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Item;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Kind;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Id;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Npc;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Count = 1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float X = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Z = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float R = 3.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Label;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Level = -1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Text;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") bool Consume = false;
};

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkQuestReward
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Xp = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Gold = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FString> Items;
};

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkQuestDef
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Id;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Title;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine", meta = (MultiLine = true)) FString Desc;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Giver;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") bool Auto = false;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") bool Final = false;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Next;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Level = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FStarkQuestStep> Steps;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FStarkQuestReward Reward;
};

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkItemDef
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Id;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Name;
	/** quest | consumable | key | equip | treasure */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Kind;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Slot;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Heal = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Atk = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Def = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Hp = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Gold = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Speed = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FLinearColor Color = FLinearColor::White;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Desc;
};

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkEnemyDef
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Kind;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Name;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Hp = 3;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Dmg = 1;
	/** metres per second */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Speed = 2.6f;
	/** metres */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Sight = 14.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Xp = 10;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Gold = 2;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") bool Ranged = false;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") bool Fly = false;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") bool Boss = false;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FLinearColor Color = FLinearColor::Red;
};

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkNpcDef
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Id;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Name;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Dialog;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Text;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FLinearColor Color = FLinearColor::White;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Level = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Age = TEXT("adult");
};

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkObjectDef
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Index = -1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Type;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float X = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Y = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Z = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Scale = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Yaw = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Kind;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Id;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Name;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Dialog;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Item;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Count = 1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Gold = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Key;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 To = -1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Lock;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Hp = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Patrol = 5.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FLinearColor Color = FLinearColor::White;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Text;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Asset;
	/** child | teen | adult (child-safety: children and teens are never enemies, targets, captured or romanced) */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Age = TEXT("adult");
};

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkLevelDef
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Index = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Name;
	/** 3d | 2d (2D chapters are built as 2.5D side-scroller maps) */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Mode;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Mood;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine", meta = (MultiLine = true)) FString Story;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString MapName;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Seed = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Size = 48.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Amp = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString TerrainKind;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Margin = 32.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Edge = 8.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") bool HasWater = false;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Water = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Weather;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float DayStart = -1.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float DayLength = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float SpawnX = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float SpawnZ = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float SpawnY = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FStarkObjectDef> Objects;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FString> Tiles;
};

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkAbilityDef
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Name;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Level = 2;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Cooldown = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Key;
};

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkDifficultyDef
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Name;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float HpMul = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float DmgMul = 1.f;
};

USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkRulesDef
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 PlayerHp = 6;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FLinearColor PlayerColor = FLinearColor(0.03f, 0.27f, 0.33f);
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FString> StartItems;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Difficulty = TEXT("normal");
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float XpBase = 40.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float XpPow = 1.45f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float InteractRadius = 2.8f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float DeathGoldKeep = 0.9f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float CritChance = 0.15f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FStarkAbilityDef> Abilities;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FStarkDifficultyDef> Difficulties;
};

/** The whole game in one struct (what the data assets add up to, or what stark_game_ue.json contains). */
USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkGameDef
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Title;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Author;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Story;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString SaveKey;
	/** Ids of child / teen characters (stark_systems child-safety stamp). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FString> Minors;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FStarkRulesDef Rules;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FStarkItemDef> Items;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FStarkEnemyDef> Enemies;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FStarkQuestDef> Quests;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FStarkDialogueDef> Dialogues;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FStarkNpcDef> Npcs;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") TArray<FStarkLevelDef> Levels;
};

/** Runtime state of one quest. */
USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkQuestProgress
{
	GENERATED_BODY()
	/** active | done */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, SaveGame, Category = "Stark World Engine") FString State;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, SaveGame, Category = "Stark World Engine") int32 Step = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, SaveGame, Category = "Stark World Engine") int32 N = 0;
};

/** What happened in the world (fed into quest steps). */
USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkEvent
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Item;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 N = 1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Kind;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Id;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString Npc;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float X = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Z = 0.f;
};

/** Derived player stats (attack, defence, max HP, speed multiplier). */
USTRUCT(BlueprintType)
struct STARKRUNTIME_API FStarkStats
{
	GENERATED_BODY()
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Atk = 1;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 Def = 0;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 MaxHp = 6;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") float Speed = 1.f;
};
