// Stark World Engine Runtime - NPCs. UStarkNpcComponent makes ANY actor a Stark World Engine NPC (talk with E, quest markers, escort
// following): put it on a MetaHuman or your own character Blueprint and set NpcId - the dialogue comes along.
// AStarkNpcCharacter is the default NPC the build script places (proxy body + MetaHuman-ready VisualClass slot).
// UActorComponent: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Components/UActorComponent
// ACharacter: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/GameFramework/ACharacter
// UChildActorComponent: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Components/UChildActorComponent
#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "GameFramework/Character.h"
#include "StarkNpc.generated.h"

class UStaticMeshComponent;
class UChildActorComponent;

UCLASS(ClassGroup = (Stark World Engine), meta = (BlueprintSpawnableComponent))
class STARKRUNTIME_API UStarkNpcComponent : public UActorComponent
{
	GENERATED_BODY()
public:
	UStarkNpcComponent();
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString NpcId;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString DialogId;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") FString DisplayName = TEXT("Villager");
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine", meta = (MultiLine = true)) FString FallbackLine;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine") int32 ObjectIndex = -1;

	/** Opens this NPC's dialogue (what pressing E next to it does). */
	UFUNCTION(BlueprintCallable, Category = "Stark World Engine") void Interact(AActor* By);
	/** "!" when the NPC offers a quest, "?" when a quest step wants you to talk to it, else empty. */
	UFUNCTION(BlueprintPure, Category = "Stark World Engine") FString Marker() const;

	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	bool bSafeSaid = false;
};

UCLASS()
class STARKRUNTIME_API AStarkNpcCharacter : public ACharacter
{
	GENERATED_BODY()
public:
	AStarkNpcCharacter();
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Stark World Engine") TObjectPtr<UStarkNpcComponent> Npc;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Stark World Engine") TObjectPtr<UStaticMeshComponent> BodyMesh;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Stark World Engine") TObjectPtr<UStaticMeshComponent> HeadMesh;
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Stark World Engine|Art") TObjectPtr<UChildActorComponent> Visual;
	/** MetaHuman-ready slot: a character Blueprint shown instead of the proxy body (metahuman_slots.csv fills it). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine|Art") TSubclassOf<AActor> VisualClass;
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stark World Engine|Art") FLinearColor Color = FLinearColor(0.7f, 0.35f, 0.1f);
	virtual void BeginPlay() override;
	virtual void OnConstruction(const FTransform& Transform) override;
};
