// Stark World Engine Runtime - game-instance subsystem (see StarkGameSubsystem.h).
// UGameplayStatics (OpenLevel, SaveGameToSlot, LoadGameFromSlot, PlaySound2D):
//   https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Kismet/UGameplayStatics
// LoadObject: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/CoreUObject/UObject/LoadObject
// FFileHelper::LoadFileToString: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Core/Misc/FFileHelper/LoadFileToString
// UWorld::SpawnActorDeferred: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Engine/UWorld/SpawnActorDeferred
#include "StarkGameSubsystem.h"
#include "StarkRules.h"
#include "StarkDataAssets.h"
#include "StarkSaveGame.h"
#include "StarkNpc.h"
#include "StarkEnemy.h"
#include "StarkWorldActors.h"
#include "StarkCharacter.h"
#include "StarkGameMode.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "Kismet/GameplayStatics.h"
#include "JsonObjectConverter.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Sound/SoundBase.h"
#include "GameFramework/PlayerController.h"

static const TCHAR* GStarkGameDataPath = TEXT("/Game/Stark/Data/DA_StarkGame.DA_StarkGame");
static const TCHAR* GStarkMapRoot = TEXT("/Game/Stark/Maps/");

void UStarkGameSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	LoadGameData();
}

void UStarkGameSubsystem::Deinitialize()
{
	if (Rules)
	{
		Rules->EnsureFoes = nullptr;
		Rules->OnWin = nullptr;
	}
	Super::Deinitialize();
}

bool UStarkGameSubsystem::LoadGameData()
{
	FStarkGameDef Def;
	bool bOk = false;
	GameData = LoadObject<UStarkGameData>(nullptr, GStarkGameDataPath);
	if (GameData && GameData->Levels.Num() > 0)
	{
		Def = GameData->BuildGameDef();
		bOk = true;
	}
	else
	{
		FString Json;
		const FString Path = FPaths::ProjectContentDir() / TEXT("Stark/Data/stark_game_ue.json");
		if (FFileHelper::LoadFileToString(Json, *Path))
		{
			bOk = FJsonObjectConverter::JsonObjectStringToUStruct(Json, &Def);
		}
	}
	if (!Rules)
	{
		Rules = NewObject<UStarkRules>(this);
	}
	Rules->Setup(Def);
	Rules->EnsureFoes = [this](const FString& Kind, int32 Need) { EnsureFoes(Kind, Need); };
	Rules->OnWin = [this]()
	{
		if (APlayerController* PC = UGameplayStatics::GetPlayerController(this, 0))
		{
			if (AStarkHUD* Hud = Cast<AStarkHUD>(PC->GetHUD()))
			{
				Hud->ShowBigText(TEXT("Victory!"), Rules->Def.Title + TEXT(" is complete"), 4.f);
			}
		}
		PlaySfx(TEXT("power"));
		OnGameWon.Broadcast();
	};
	bLoaded = bOk;
	if (!bOk)
	{
		UE_LOG(LogTemp, Warning, TEXT("[Stark World Engine] no game data: build the levels (menu Stark World Engine > Rebuild from Stark World Engine)"));
	}
	return bOk;
}

void UStarkGameSubsystem::NewGame()
{
	if (!Rules) { LoadGameData(); }
	Rules->bInvulnerable = bTestInvulnerable;
	Rules->NewGame();
	bHasPendingPos = false;
	bPorting = false;
	Modal.Reset();
	Changed();
}

void UStarkGameSubsystem::LevelReady(UWorld* World)
{
	if (!Rules || Rules->Def.Levels.Num() == 0) { LoadGameData(); }
	if (!bBooted)
	{
		bBooted = true;
		NewGame();
	}
	Rules->bInvulnerable = bTestInvulnerable;
	const FString MapName = UGameplayStatics::GetCurrentLevelName(World, true);
	int32 Index = Rules->LevelIndex;
	for (const FStarkLevelDef& L : Rules->Def.Levels)
	{
		if (L.MapName == MapName) { Index = L.Index; }
	}
	bPorting = false;
	Rules->StartLevelQuests(Index);
	if (const FStarkLevelDef* L = Rules->FindLevel(Index))
	{
		if (APlayerController* PC = UGameplayStatics::GetPlayerController(this, 0))
		{
			if (AStarkHUD* Hud = Cast<AStarkHUD>(PC->GetHUD()))
			{
				Hud->ShowBigText(L->Name, L->Story.Left(160), 3.2f);
			}
		}
	}
	if (bHasPendingPos)
	{
		if (AStarkPlayerCharacter* P = GetPlayer())
		{
			P->TeleportToPlan(PendingPos.X, PendingPos.Y);
			bHasPendingPos = false;
		}
	}
	OnLevelStarted.Broadcast(Index);
	Changed();
}

void UStarkGameSubsystem::TravelToLevel(int32 Index)
{
	const FStarkLevelDef* L = Rules ? Rules->FindLevel(Index) : nullptr;
	if (!L || bPorting) { return; }
	bPorting = true;
	const int32 From = Rules->LevelIndex;
	Rules->LevelIndex = Index;
	if (Index != From) { SaveToSlot(TEXT("auto"), true); }
	PlaySfx(TEXT("portal"));
	UGameplayStatics::OpenLevel(this, FName(*(FString(GStarkMapRoot) + L->MapName)));
}

int32 UStarkGameSubsystem::GetLevelIndex() const { return Rules ? Rules->LevelIndex : 0; }
int32 UStarkGameSubsystem::GetLevelCount() const { return Rules ? Rules->Def.Levels.Num() : 0; }

FStarkLevelDef UStarkGameSubsystem::GetLevelDef(int32 Index) const
{
	const FStarkLevelDef* L = Rules ? Rules->FindLevel(Index) : nullptr;
	return L ? *L : FStarkLevelDef();
}

bool UStarkGameSubsystem::IsSideView() const
{
	const FStarkLevelDef* L = Rules ? Rules->FindLevel(Rules->LevelIndex) : nullptr;
	return L && L->Mode == TEXT("2d");
}

float UStarkGameSubsystem::TerrainHeightAt(float PlanX, float PlanZ) const
{
	return Rules ? Rules->TerrainHeight(Rules->LevelIndex, PlanX, PlanZ) : 0.f;
}

float UStarkGameSubsystem::WaterDepthAt(float PlanX, float PlanZ) const
{
	return Rules ? Rules->WaterDepth(Rules->LevelIndex, PlanX, PlanZ) : -9.f;
}

// ---------------------------------------------------------------- saves
FString UStarkGameSubsystem::SlotName(const FString& Slot) const
{
	return FString::Printf(TEXT("Stark_%s_%s"), Rules ? *Rules->Def.SaveKey : TEXT("game"), *Slot);
}

bool UStarkGameSubsystem::SaveToSlot(const FString& Slot, bool bQuiet)
{
	if (!Rules) { return false; }
	UStarkSaveGame* S = Cast<UStarkSaveGame>(UGameplayStatics::CreateSaveGameObject(UStarkSaveGame::StaticClass()));
	if (!S) { return false; }
	S->SaveKey = Rules->Def.SaveKey;
	S->LevelIndex = Rules->LevelIndex;
	if (AStarkPlayerCharacter* P = GetPlayer())
	{
		S->bHasPos = true;
		S->PosXZ = P->GetPlanXZ();
	}
	S->Hp = Rules->Hp;
	S->Lvl = Rules->Lvl;
	S->Xp = Rules->Xp;
	S->Gold = Rules->Gold;
	S->Score = Rules->Score;
	S->Inventory = Rules->Inventory;
	S->Equipped = Rules->Equipped;
	S->Quests = Rules->Quests;
	S->Gone = Rules->Gone.Array();
	S->Flags = Rules->Flags.Array();
	S->CheckpointLevel = Rules->CheckpointLevel;
	S->Checkpoint = Rules->Checkpoint;
	S->bWon = Rules->bWon;
	S->Difficulty = Rules->Difficulty;
	S->SavedAt = FDateTime::Now();
	const bool bOk = UGameplayStatics::SaveGameToSlot(S, SlotName(Slot), 0);
	if (!bQuiet)
	{
		Rules->Toast(bOk ? (Slot == TEXT("auto") ? TEXT("Saved to autosave") : TEXT("Saved to slot ") + Slot) : TEXT("Could not save"), TEXT("l"));
		Changed();
	}
	return bOk;
}

bool UStarkGameSubsystem::LoadFromSlot(const FString& Slot)
{
	if (!Rules) { return false; }
	UStarkSaveGame* S = Cast<UStarkSaveGame>(UGameplayStatics::LoadGameFromSlot(SlotName(Slot), 0));
	if (!S || !Rules->Def.Levels.IsValidIndex(S->LevelIndex))
	{
		Rules->Toast(TEXT("That slot is empty"));
		Changed();
		return false;
	}
	Rules->Hp = S->Hp;
	Rules->Lvl = FMath::Max(1, S->Lvl);
	Rules->Xp = S->Xp;
	Rules->Gold = S->Gold;
	Rules->Score = S->Score;
	Rules->Inventory = S->Inventory;
	Rules->Equipped = S->Equipped;
	Rules->Quests = S->Quests;
	Rules->Gone.Reset();
	for (const FString& K : S->Gone) { Rules->Gone.Add(K); }
	Rules->Flags.Reset();
	for (const FString& K : S->Flags) { Rules->Flags.Add(K); }
	Rules->CheckpointLevel = S->CheckpointLevel;
	Rules->Checkpoint = S->Checkpoint;
	Rules->bWon = S->bWon;
	if (!S->Difficulty.IsEmpty()) { Rules->Difficulty = S->Difficulty; }
	Rules->LevelIndex = S->LevelIndex;
	Rules->CloseDialogue();
	Modal.Reset();
	bHasPendingPos = S->bHasPos;
	PendingPos = S->PosXZ;
	bPorting = false;
	Rules->Toast(Slot == TEXT("auto") ? TEXT("Loaded autosave") : TEXT("Loaded slot ") + Slot, TEXT("l"));
	FlushToasts();
	UGameplayStatics::OpenLevel(this, FName(*(FString(GStarkMapRoot) + Rules->Def.Levels[S->LevelIndex].MapName)));
	return true;
}

FString UStarkGameSubsystem::SlotInfo(const FString& Slot) const
{
	if (!Rules || !UGameplayStatics::DoesSaveGameExist(SlotName(Slot), 0)) { return FString(); }
	const UStarkSaveGame* S = Cast<UStarkSaveGame>(UGameplayStatics::LoadGameFromSlot(SlotName(Slot), 0));
	if (!S || !Rules->Def.Levels.IsValidIndex(S->LevelIndex)) { return FString(); }
	return FString::Printf(TEXT("Lv %d - %s - %s"), S->Lvl, *Rules->Def.Levels[S->LevelIndex].Name, *S->SavedAt.ToString(TEXT("%Y-%m-%d %H:%M")));
}

void UStarkGameSubsystem::DeleteSlot(const FString& Slot)
{
	UGameplayStatics::DeleteGameInSlot(SlotName(Slot), 0);
}

// ---------------------------------------------------------------- dialogue + inventory wrappers
void UStarkGameSubsystem::Talk(const FString& NpcId, const FString& DialogId, const FString& Name, const FString& FallbackLine)
{
	if (!Rules) { return; }
	Rules->Talk(NpcId, DialogId, Name, FallbackLine);
	PlaySfx(TEXT("talk"));
	Changed();
}

void UStarkGameSubsystem::Choose(int32 Index)
{
	if (!Rules) { return; }
	Rules->Choose(Index);
	if (!Rules->bDialogueOpen) { BusyTime = 0.25f; }
	PlaySfx(TEXT("talk"));
	Changed();
}

void UStarkGameSubsystem::CloseDialogue()
{
	if (!Rules) { return; }
	Rules->CloseDialogue();
	BusyTime = 0.25f;
	Changed();
}

bool UStarkGameSubsystem::IsDialogueOpen() const { return Rules && Rules->bDialogueOpen; }
void UStarkGameSubsystem::GiveItem(const FString& Id, int32 N, bool bQuiet) { if (Rules) { Rules->Give(Id, N, bQuiet); Changed(); } }
bool UStarkGameSubsystem::TakeItem(const FString& Id, int32 N) { const bool b = Rules && Rules->Take(Id, N); Changed(); return b; }
bool UStarkGameSubsystem::HasItem(const FString& Id, int32 N) const { return Rules && Rules->Has(Id, N); }
void UStarkGameSubsystem::UseItem(const FString& Id) { if (Rules) { Rules->UseItem(Id); Changed(); } }
void UStarkGameSubsystem::Quaff() { if (Rules) { Rules->Quaff(); Changed(); } }
void UStarkGameSubsystem::StartQuest(const FString& Id) { if (Rules) { Rules->StartQuest(Id); Changed(); } }
FString UStarkGameSubsystem::QuestState(const FString& Id) const { return Rules ? Rules->QuestState(Id) : FString(); }
void UStarkGameSubsystem::QuestEvent(const FString& Type, const FStarkEvent& Data) { if (Rules) { Rules->Event(Type, Data); Changed(); } }
FStarkStats UStarkGameSubsystem::GetStats() const { return Rules ? Rules->Stats() : FStarkStats(); }
bool UStarkGameSubsystem::IsWon() const { return Rules && Rules->bWon; }

bool UStarkGameSubsystem::IsBusy() const
{
	return (Rules && Rules->bDialogueOpen) || !Modal.IsEmpty() || BusyTime > 0.f;
}

TArray<FString> UStarkGameSubsystem::TrackerLines() const
{
	TArray<FString> Out;
	if (!Rules) { return Out; }
	for (const FStarkQuestDef* Q : Rules->ActiveQuests())
	{
		const FStarkQuestStep* S = Rules->CurrentStep(*Q);
		if (!S) { continue; }
		const FStarkQuestProgress* P = Rules->Quests.Find(Q->Id);
		const int32 C = FMath::Max(1, S->Count);
		Out.Add(Q->Title);
		Out.Add(TEXT("  ") + Rules->StepText(*S) + (C > 1 && P ? FString::Printf(TEXT(" - %d/%d"), P->N, C) : FString()));
		if (Out.Num() >= 6) { break; }
	}
	return Out;
}

// ---------------------------------------------------------------- world helpers
FString UStarkGameSubsystem::GoneKey(int32 ObjectIndex) const
{
	return FString::Printf(TEXT("%d:%d"), Rules ? Rules->LevelIndex : 0, ObjectIndex);
}

bool UStarkGameSubsystem::IsGone(const FString& Key) const { return Rules && !Key.IsEmpty() && Rules->Gone.Contains(Key); }
void UStarkGameSubsystem::MarkGone(const FString& Key) { if (Rules && !Key.IsEmpty()) { Rules->Gone.Add(Key); } }

void UStarkGameSubsystem::SetCheckpoint(const FVector2D& PlanXZ)
{
	if (!Rules) { return; }
	if (Rules->CheckpointLevel == Rules->LevelIndex && (Rules->Checkpoint - PlanXZ).Size() < 0.5f) { return; }
	Rules->CheckpointLevel = Rules->LevelIndex;
	Rules->Checkpoint = PlanXZ;
	Rules->Hp = (float)Rules->Stats().MaxHp;
	SaveToSlot(TEXT("auto"), true);
	Rules->Toast(TEXT("Checkpoint - progress saved"), TEXT("l"));
	PlaySfx(TEXT("power"));
	Changed();
}

void UStarkGameSubsystem::OnPlayerHit(float Damage)
{
	if (!Rules) { return; }
	Rules->bInvulnerable = bTestInvulnerable;
	if (Rules->Hurt(Damage))
	{
		if (APlayerController* PC = UGameplayStatics::GetPlayerController(this, 0))
		{
			if (AStarkHUD* Hud = Cast<AStarkHUD>(PC->GetHUD()))
			{
				Hud->ShowBigText(TEXT("You fell..."), TEXT("Back to the last checkpoint. (Lost 10% gold)"), 2.2f);
			}
		}
		if (AStarkPlayerCharacter* P = GetPlayer())
		{
			P->Respawn(Rules->CheckpointLevel == Rules->LevelIndex, Rules->Checkpoint);
		}
	}
	PlaySfx(TEXT("hit"));
	Changed();
}

void UStarkGameSubsystem::Changed()
{
	FlushToasts();
	OnChanged.Broadcast();
}

void UStarkGameSubsystem::FlushToasts()
{
	if (!Rules) { return; }
	TArray<TPair<FString, FString>> Pending = MoveTemp(Rules->PendingToasts);
	Rules->PendingToasts.Reset();
	AStarkHUD* Hud = nullptr;
	if (APlayerController* PC = UGameplayStatics::GetPlayerController(this, 0)) { Hud = Cast<AStarkHUD>(PC->GetHUD()); }
	for (const TPair<FString, FString>& T : Pending)
	{
		if (Hud) { Hud->AddToast(T.Key, T.Value); }
		OnToast.Broadcast(T.Key, T.Value);
		UE_LOG(LogTemp, Log, TEXT("[Stark World Engine] %s"), *T.Key);
	}
}

void UStarkGameSubsystem::PlaySfx(const FString& Name)
{
	if (!GameData) { return; }
	if (const TSoftObjectPtr<USoundBase>* Soft = GameData->Sounds.Find(Name))
	{
		if (USoundBase* Sound = Soft->LoadSynchronous())
		{
			UGameplayStatics::PlaySound2D(this, Sound);
		}
	}
}

void UStarkGameSubsystem::Tick(float DeltaSeconds)
{
	if (BusyTime > 0.f) { BusyTime -= DeltaSeconds; }
	if (Rules) { Rules->TickCooldowns(DeltaSeconds); }
	FlushToasts();
}

// ---------------------------------------------------------------- registries
void UStarkGameSubsystem::RegisterNpc(UStarkNpcComponent* Npc) { NpcList.AddUnique(Npc); }
void UStarkGameSubsystem::UnregisterNpc(UStarkNpcComponent* Npc) { NpcList.Remove(Npc); }
void UStarkGameSubsystem::RegisterEnemy(AStarkEnemyCharacter* Enemy) { EnemyList.AddUnique(Enemy); }
void UStarkGameSubsystem::UnregisterEnemy(AStarkEnemyCharacter* Enemy) { EnemyList.Remove(Enemy); }
void UStarkGameSubsystem::RegisterInteractable(AStarkInteractable* Thing) { InteractableList.AddUnique(Thing); }
void UStarkGameSubsystem::UnregisterInteractable(AStarkInteractable* Thing) { InteractableList.Remove(Thing); }

TArray<UStarkNpcComponent*> UStarkGameSubsystem::Npcs() const
{
	TArray<UStarkNpcComponent*> Out;
	for (const TWeakObjectPtr<UStarkNpcComponent>& W : NpcList) { if (W.IsValid()) { Out.Add(W.Get()); } }
	return Out;
}

TArray<AStarkEnemyCharacter*> UStarkGameSubsystem::Enemies() const
{
	TArray<AStarkEnemyCharacter*> Out;
	for (const TWeakObjectPtr<AStarkEnemyCharacter>& W : EnemyList)
	{
		if (W.IsValid() && !W->bDead && !W->IsProtected()) { Out.Add(W.Get()); }     // minors are never targets
	}
	return Out;
}

TArray<AStarkInteractable*> UStarkGameSubsystem::Interactables() const
{
	TArray<AStarkInteractable*> Out;
	for (const TWeakObjectPtr<AStarkInteractable>& W : InteractableList) { if (W.IsValid()) { Out.Add(W.Get()); } }
	return Out;
}

AStarkPlayerCharacter* UStarkGameSubsystem::GetPlayer() const
{
	return Cast<AStarkPlayerCharacter>(UGameplayStatics::GetPlayerCharacter(this, 0));
}

void UStarkGameSubsystem::EnsureFoes(const FString& Kind, int32 Need)
{
	UWorld* World = GetWorld();
	if (!World || !Rules || Need <= 0) { return; }
	const FString Want = Kind.IsEmpty() ? FString(TEXT("any")) : Kind;
	auto Matches = [&Want](const FString& K, bool bBoss) { return (Want == TEXT("boss")) == bBoss && (Want == TEXT("any") || K == Want); };
	int32 Alive = 0;
	TArray<FVector> Homes;
	for (AStarkEnemyCharacter* E : Enemies())
	{
		if (Matches(E->Kind, E->IsBoss())) { ++Alive; }
		if (!E->IsBoss()) { Homes.Add(E->Home); }
	}
	const FStarkLevelDef* L = Rules->FindLevel(Rules->LevelIndex);
	if (!L || L->Mode == TEXT("2d")) { return; }
	auto Spawn = [&](const FStarkObjectDef& O, const FVector& Loc)
	{
		const FTransform Xf(FRotator::ZeroRotator, Loc);
		AStarkEnemyCharacter* E = World->SpawnActorDeferred<AStarkEnemyCharacter>(AStarkEnemyCharacter::StaticClass(), Xf,
			nullptr, nullptr, ESpawnActorCollisionHandlingMethod::AdjustIfPossibleButAlwaysSpawn);
		if (!E) { return; }
		E->ObjectIndex = O.Index;
		E->Age = O.Age.IsEmpty() ? FString(TEXT("adult")) : O.Age;
		E->Kind = O.Kind.IsEmpty() ? FString(TEXT("grunt")) : O.Kind;
		E->HpOverride = O.Hp;
		E->Patrol = O.Patrol;
		E->SizeScale = O.Scale;
		E->FinishSpawning(Xf);
	};
	for (const FStarkObjectDef& O : L->Objects)
	{
		if (Alive >= Need) { break; }
		if (O.Type != TEXT("enemy") || !O.Id.IsEmpty() || !Matches(O.Kind, O.Kind == TEXT("boss"))) { continue; }
		if (Rules->IsMinor(O.Id, O.Age)) { continue; }
		const FString Key = GoneKey(O.Index);
		if (!Rules->Gone.Contains(Key)) { continue; }
		Rules->Gone.Remove(Key);
		Spawn(O, StarkToUE(O.X, O.Y + 0.6f, O.Z));
		++Alive;
	}
	int32 Tries = 0;
	while (Alive < Need && Tries++ < 60)
	{
		FVector2D P;
		if (Homes.Num() > 0)
		{
			const FVector2D H = UEToStarkXZ(Homes[Tries % Homes.Num()]);
			P = H + FVector2D(FMath::FRandRange(-3.f, 3.f), FMath::FRandRange(-3.f, 3.f));
		}
		else
		{
			const FVector2D Me = GetPlayer() ? GetPlayer()->GetPlanXZ() : FVector2D::ZeroVector;
			const float A = FMath::FRand() * 2.f * PI;
			P = Me + FVector2D(FMath::Cos(A), FMath::Sin(A)) * 14.f;
		}
		const float Lim = L->Size - 2.f;
		P.X = FMath::Clamp(P.X, -Lim, Lim);
		P.Y = FMath::Clamp(P.Y, -Lim, Lim);
		if (Rules->WaterDepth(Rules->LevelIndex, P.X, P.Y) > 0.8f) { continue; }
		FStarkObjectDef O;
		O.Kind = Want == TEXT("any") ? FString(TEXT("grunt")) : Want;
		Spawn(O, StarkToUE(P.X, Rules->TerrainHeight(Rules->LevelIndex, P.X, P.Y) + 0.6f, P.Y));
		++Alive;
	}
}
